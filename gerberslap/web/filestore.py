"""The Gerber files the server has read, by hash. The browser holds the layout and refers to files by hash; this is where the
pipeline finds their bytes. Bounded, so that opening many boards cannot fill the memory: the least recently used go first (a
project whose files were dropped gets `file_missing` and has to be opened again)."""
import threading
from collections import OrderedDict
from collections.abc import Mapping


class StoreFull(Exception):
    pass


class FileStore(Mapping):
    def __init__(self, max_bytes: int = 1 << 30):
        self.max_bytes = max_bytes
        self._items: OrderedDict = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def add(self, files: Mapping) -> None:
        """Keep these files (sha256 -> bytes). All or none: a batch larger than the whole store is refused."""
        with self._lock:
            new = {k: v for k, v in files.items() if k not in self._items}
            if sum(len(v) for v in new.values()) > self.max_bytes:
                raise StoreFull("these files are larger than the whole store")
            for k in files:                                    # files already known count as used just now
                if k in self._items:
                    self._items.move_to_end(k)
            for k, v in new.items():
                self._items[k] = v
                self._bytes += len(v)
            while self._bytes > self.max_bytes:
                _, dropped = self._items.popitem(last=False)
                self._bytes -= len(dropped)

    def __getitem__(self, key):
        with self._lock:
            value = self._items[key]
            self._items.move_to_end(key)
            return value

    def __iter__(self):
        with self._lock:
            return iter(list(self._items))

    def __len__(self):
        return len(self._items)

    @property
    def size_bytes(self) -> int:
        return self._bytes
