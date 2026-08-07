"""User settings, persisted as TOML under the platform config directory."""

from __future__ import annotations

import tomllib
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field

APP_NAME = "mupstudio"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME))


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME))


def engines_dir() -> Path:
    """Where `mupstudio get-engines` puts downloaded executables."""
    return data_dir() / "bin"


def settings_path() -> Path:
    return config_dir() / "settings.toml"


class Settings(BaseModel):
    """Machine-level settings. Project content never lives here."""

    mf6_exe: str | None = Field(default=None, description="Path to the mf6 executable")
    mf2005_exe: str | None = Field(default=None, description="Path to the mf2005 executable")
    pht3d_exe: str | None = Field(default=None, description="Path to the PHT3D executable")
    gridgen_exe: str | None = Field(default=None, description="Path to the gridgen executable")
    database_dirs: list[str] = Field(
        default_factory=list, description="Extra directories to scan for PHREEQC .dat databases"
    )
    max_concurrent_runs: int = Field(default=2, ge=1, le=32)
    default_crs: str | None = Field(default=None, description="EPSG code used for new projects")

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or settings_path()
        if not path.exists():
            return cls()
        with path.open("rb") as fh:
            return cls.model_validate(tomllib.load(fh))

    def save(self, path: Path | None = None) -> Path:
        path = path or settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for name, value in self.model_dump(exclude_none=True).items():
            if isinstance(value, str):
                lines.append(f'{name} = "{value}"')
            elif isinstance(value, list):
                items = ", ".join(f'"{item}"' for item in value)
                lines.append(f"{name} = [{items}]")
            else:
                lines.append(f"{name} = {value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
