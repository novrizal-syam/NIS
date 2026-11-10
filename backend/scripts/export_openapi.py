"""Write the OpenAPI spec to docs/api/openapi.json (run after API changes):

python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def main() -> None:
    spec = create_app().openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{len(spec['paths'])} paths -> {OUT}")


if __name__ == "__main__":
    main()
