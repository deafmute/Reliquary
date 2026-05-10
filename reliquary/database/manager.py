import json
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIG_DIR = Path.home() / '.config' / 'reliquary'
CONNECTIONS_FILE = CONFIG_DIR / 'connections.json'

DEFAULT_PORTS = {
    'postgresql': 5432,
    'mysql': 3306,
}


@dataclass
class ConnectionConfig:
    id: str
    name: str
    driver: str  # 'sqlite', 'postgresql', 'mysql'
    file_path: str = ''
    host: str = 'localhost'
    port: int = 5432
    database: str = ''
    username: str = ''
    password: str = ''

    def get_url(self) -> str:
        if self.driver == 'sqlite':
            return f'sqlite:///{self.file_path}'
        auth = ''
        if self.username:
            import urllib.parse
            pw = urllib.parse.quote_plus(self.password) if self.password else ''
            auth = f'{urllib.parse.quote_plus(self.username)}:{pw}@'
        db = f'/{self.database}' if self.database else ''
        if self.driver == 'postgresql':
            return f'postgresql+psycopg2://{auth}{self.host}:{self.port}{db}'
        if self.driver == 'mysql':
            return f'mysql+pymysql://{auth}{self.host}:{self.port}{db}'
        raise ValueError(f'Unknown driver: {self.driver}')

    def get_display_host(self) -> str:
        if self.driver == 'sqlite':
            return Path(self.file_path).name or 'SQLite'
        return f'{self.host}:{self.port}'

    @classmethod
    def make_new(cls, **kwargs) -> 'ConnectionConfig':
        return cls(id=str(uuid.uuid4()), **kwargs)


class ConnectionManager:
    def __init__(self):
        self._configs: dict[str, ConnectionConfig] = {}
        self._load()

    def _load(self):
        if not CONNECTIONS_FILE.exists():
            return
        try:
            with open(CONNECTIONS_FILE) as f:
                data = json.load(f)
            for item in data:
                cfg = ConnectionConfig(**item)
                self._configs[cfg.id] = cfg
        except Exception:
            pass

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONNECTIONS_FILE, 'w') as f:
            json.dump([asdict(c) for c in self._configs.values()], f, indent=2)

    def add(self, config: ConnectionConfig):
        self._configs[config.id] = config
        self.save()

    def update(self, config: ConnectionConfig):
        self._configs[config.id] = config
        self.save()

    def remove(self, config_id: str):
        self._configs.pop(config_id, None)
        self.save()

    def get_all(self) -> list[ConnectionConfig]:
        return list(self._configs.values())

    def get(self, config_id: str) -> Optional[ConnectionConfig]:
        return self._configs.get(config_id)
