import sys
from pathlib import Path

_ecom_dir = Path(__file__).resolve().parent.parent / "ecom"
if str(_ecom_dir) not in sys.path:
    sys.path.insert(0, str(_ecom_dir))

_ecom_app_dir = _ecom_dir / "app"
if str(_ecom_app_dir) not in __path__:
    __path__.insert(0, str(_ecom_app_dir))

