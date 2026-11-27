import fsspec
import obstore.store
import pytest
import s3fs
from fsspec.implementations.local import LocalFileSystem

from benchmark_datasets.s3 import (
    S3Config,
    exists,
    filesystem,
    glob,
    obstore_store,
    public_href,
    public_prefix,
    remove,
    s3_filesystem,
)

ENV_VARS = ("BUCKET", "AWS_ENDPOINT_URL", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Make sure no S3 settings leak in from the environment (e.g. from a .env file)."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def s3_env(monkeypatch):
    env = dict(zip(ENV_VARS, ("bucket", "https://objectstore.example.com", "region", "key", "secret"), strict=True))
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    return env


@pytest.fixture
def memory_fs():
    fs = fsspec.filesystem("memory")
    fs.pipe({"/data/a.tif": b"a", "/data/b.TIF": b"b", "/data/c.txt": b"c"})
    yield fs
    fs.rm("/data", recursive=True)


def test_s3_config_from_env_loads_from_environment(s3_env):
    s3_config = S3Config.from_env()
    assert s3_config == S3Config(
        bucket="bucket",
        endpoint_url="https://objectstore.example.com",
        region="region",
        access_key_id="key",
        secret_access_key="secret",
    )


def test_s3_config_from_env_prefers_arguments_over_environment(s3_env):
    s3_config = S3Config.from_env(bucket="other-bucket", access_key_id="other-key")
    assert s3_config.bucket == "other-bucket"
    assert s3_config.access_key_id == "other-key"
    assert s3_config.secret_access_key == "secret"


def test_s3_config_from_env_without_environment_is_empty():
    assert S3Config.from_env() == S3Config()


def test_s3_config_returns_anonymous_if_key_and_secret_are_not_set():
    assert S3Config().is_anonymous
    assert not S3Config(access_key_id="key", secret_access_key="secret").is_anonymous
    assert not S3Config(access_key_id="key").is_anonymous
    assert not S3Config(secret_access_key="secret").is_anonymous


def test_s3_filesystem_caches_the_filesystem_object():
    s3_filesystem.cache_clear()
    s3_config = S3Config(access_key_id="key", secret_access_key="secret")
    fs = s3_filesystem(s3_config)
    fs_new = s3_filesystem(S3Config(access_key_id="key", secret_access_key="secret"))
    assert fs is fs_new
    assert s3_filesystem.cache_info().hits == 1


def test_s3_filesystem_uses_config():
    s3_config = S3Config(
        endpoint_url="https://objectstore.example.com", region="region", access_key_id="key", secret_access_key="secret"
    )
    fs = s3_filesystem(s3_config)
    assert fs.storage_options == {
        "anon": False,
        "endpoint_url": "https://objectstore.example.com",
        "client_kwargs": {"region_name": "region"},
        "key": "key",
        "secret": "secret",
    }


def test_s3_filesystem_is_anonymous_without_credentials():
    assert s3_filesystem(S3Config()).anon


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("s3://bucket/key", s3fs.S3FileSystem),
        ("/local/path", LocalFileSystem),
        ("relative/path", LocalFileSystem),
        ("file:///local/path", LocalFileSystem),
    ],
)
def test_filesystem_matches_protocol(uri, expected):
    assert isinstance(filesystem(uri, S3Config()), expected)


def test_filesystem_falls_back_to_s3_config_from_environment(s3_env):
    fs = filesystem("s3://bucket/key")
    assert fs.key == "key"
    assert fs.endpoint_url == "https://objectstore.example.com"


def test_exists(tmp_path):
    (tmp_path / "a.tif").touch()
    assert exists(str(tmp_path / "a.tif"))
    assert exists(str(tmp_path))
    assert not exists(str(tmp_path / "b.tif"))


def test_glob_local_returns_sorted_paths(tmp_path):
    for name in ("b.tif", "a.tif", "c.txt"):
        (tmp_path / name).touch()
    assert glob(f"{tmp_path}/*.tif") == [str(tmp_path / "a.tif"), str(tmp_path / "b.tif")]


def test_glob_with_protocol_returns_full_uris(memory_fs):
    assert glob("memory:///data/*.[tT][iI][fF]") == ["memory:///data/a.tif", "memory:///data/b.TIF"]


def test_glob_without_matches_returns_empty_list(tmp_path):
    assert glob(f"{tmp_path}/*.tif") == []


def test_remove_file(tmp_path):
    path = tmp_path / "a.tif"
    path.touch()
    remove(str(path))
    assert not path.exists()


def test_remove_directory_recursively(tmp_path):
    (tmp_path / "dir" / "sub").mkdir(parents=True)
    (tmp_path / "dir" / "sub" / "a.tif").touch()
    remove(str(tmp_path / "dir"))
    assert not (tmp_path / "dir").exists()


def test_remove_missing_path_does_not_fail(tmp_path):
    remove(str(tmp_path / "missing"))


def test_public_prefix_with_custom_endpoint():
    s3_config = S3Config(endpoint_url="https://objectstore.example.com")
    assert public_prefix("s3://bucket/key", s3_config) == "https://objectstore.example.com/bucket/"


def test_public_prefix_defaults_to_aws():
    assert public_prefix("s3://bucket/key", S3Config()) == "https://bucket.s3.amazonaws.com/"


def test_public_prefix_falls_back_to_s3_config_from_environment(s3_env):
    assert public_prefix("s3://bucket/key") == "https://objectstore.example.com/bucket/"


@pytest.mark.parametrize(
    ("uri", "endpoint_url", "expected"),
    [
        (
            "s3://bucket/dir/a.tif",
            "https://objectstore.example.com",
            "https://objectstore.example.com/bucket/dir/a.tif",
        ),
        ("s3://bucket/dir/a.tif", None, "https://bucket.s3.amazonaws.com/dir/a.tif"),
        # only the bucket is replaced, not a later occurrence of the same string
        ("s3://bucket/s3://bucket/a.tif", None, "https://bucket.s3.amazonaws.com/s3://bucket/a.tif"),
        # non-S3 URIs are returned as they are
        ("https://example.com/a.tif", None, "https://example.com/a.tif"),
        ("/local/a.tif", None, "/local/a.tif"),
    ],
)
def test_public_href(uri, endpoint_url, expected):
    assert public_href(uri, S3Config(endpoint_url=endpoint_url)) == expected


def test_obstore_store_s3_uses_config():
    s3_config = S3Config(
        endpoint_url="https://objectstore.example.com", region="region", access_key_id="key", secret_access_key="secret"
    )
    store = obstore_store("s3://bucket/prefix", s3_config)
    assert isinstance(store, obstore.store.S3Store)
    assert store.prefix == "prefix"
    assert store.config["bucket"] == "bucket"
    assert store.config["endpoint"] == "https://objectstore.example.com"
    assert store.config["region"] == "region"
    assert store.config["access_key_id"] == "key"
    assert store.config["secret_access_key"] == "secret"
    assert "skip_signature" not in store.config


def test_obstore_store_s3_anonymous_skips_signature():
    store = obstore_store("s3://bucket", S3Config())
    assert store.config["skip_signature"] == "true"  # obstore returns config values as strings


def test_obstore_store_http():
    assert isinstance(obstore_store("https://example.com/dir"), obstore.store.HTTPStore)


def test_obstore_store_local_creates_directory(tmp_path):
    path = tmp_path / "new" / "dir"
    store = obstore_store(str(path))
    assert isinstance(store, obstore.store.LocalStore)
    assert path.is_dir()
