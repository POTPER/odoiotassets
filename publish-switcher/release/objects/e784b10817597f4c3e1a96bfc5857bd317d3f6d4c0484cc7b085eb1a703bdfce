"""核心同步 API 兼容层。

旧脚本写「import core」时，从此处导出 Engine、Source、SyncError 等，
实际实现已在 publish_switcher 包内。
"""
from publish_switcher.common.errors import (
    SyncError,
    Cancelled,
    check_cancel,
)
from publish_switcher.common.files import (
    atomic_json,
    fsync_dir,
    read_json,
    relative_path,
    operation_lock,
)
from publish_switcher.sync.hashes import (
    digest,
    fingerprints,
    hash_field,
    content_matches,
    equivalent,
)
from publish_switcher.sync.manifests import (
    managed,
    asset_file,
    sync_blockers,
    sha_value,
    validate_source,
    validate_manifest,
    validate_catalog,
)
from publish_switcher.sync.scan import (
    scan,
)
from publish_switcher.repositories.source import (
    AccessDenied,
    NETWORK_ATTEMPTS,
    transient_network_error,
    retry_pause,
    HTTPSOnly,
    Source,
    load_profile,
)
from publish_switcher.sync.engine import (
    assert_stopped,
    Engine,
)

from publish_switcher.sync.formats import DEFAULT_EXTENSIONS, LEGACY_EXTENSIONS, normalize_extensions, file_extension, describe
