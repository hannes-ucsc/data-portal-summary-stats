from typing import (
    Optional,
    FrozenSet,
)

from attr import dataclass


@dataclass
class MatrixInfo:
    source: str
    project_uuid: str
    zip_path: Optional[str]
    extract_path: str
    lib_con_approaches: FrozenSet[str] = frozenset()

    @property
    def figures_folder(self) -> str:
        use_lca_dir = self.lib_con_approaches is not None and len(self.lib_con_approaches) > 1
        return f'{self.project_uuid}/' + (f'{self.lib_con_approaches}/' if use_lca_dir else '')
