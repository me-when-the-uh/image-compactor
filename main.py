"""Entry point and build-time checks for Image Compactor."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# The package directory is the repository root. Add its parent for the source run.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _write_log(path: str | None, lines: list[str]) -> None:
    if path:
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verify_encoder(log_path: str | None) -> int:
    lines: list[str] = []
    code = 1
    try:
        from PIL import Image

        from image_compactor.encode import encode_image, find_avifenc
        from image_compactor.facts import inspect_image
        from image_compactor.suggest import decide

        encoder = find_avifenc()
        lines.append(f"encoder={encoder}")
        with tempfile.TemporaryDirectory(prefix="image-compactor-verify-") as temp_name:
            folder = Path(temp_name)
            source = folder / "verify.jpg"
            Image.new("RGB", (64, 48), (20, 180, 40)).save(source, quality=92)
            facts = inspect_image(source)
            decision = decide(
                facts,
                phone_override="auto",
                speed=3,
                quality=45,
                bit_depth=10,
                downscale="off",
                percent=75,
                tag_p3=True,
            )
            result = encode_image(source, folder, decision, avifenc=encoder, threads=1)
            lines.append(f"output={result.output.name}")
            lines.append(f"bytes={result.bytes_out}")
            with Image.open(result.output) as image:
                lines.append(f"size={image.size[0]}x{image.size[1]}")
                lines.append(f"mode={image.mode}")
        lines.append("ok=True")
        code = 0
    except Exception as exc:
        lines.append("ok=False")
        lines.append(f"error={exc}")
    _write_log(log_path, lines)
    return code


def _verify_ui(log_path: str | None) -> int:
    lines: list[str] = []
    code = 1
    try:
        from tkinterdnd2 import TkinterDnD

        from image_compactor.gui import App

        root = TkinterDnD.Tk()
        root.withdraw()
        try:
            app = App(root)
            root.update()
            ready = bool(app.avifenc and app.dnd_ready)
            lines.append(f"encoder={app.avifenc}")
            lines.append(f"dnd_ready={app.dnd_ready}")
            lines.append(f"ready={ready}")
            code = 0 if ready else 1
        finally:
            root.destroy()
    except Exception as exc:
        lines.append("ready=False")
        lines.append(f"error={exc}")
    _write_log(log_path, lines)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--verify-encoder", metavar="LOG")
    parser.add_argument("--verify-ui", metavar="LOG")
    args = parser.parse_args()
    if args.verify_encoder:
        return _verify_encoder(args.verify_encoder)
    if args.verify_ui:
        return _verify_ui(args.verify_ui)

    from image_compactor.gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
