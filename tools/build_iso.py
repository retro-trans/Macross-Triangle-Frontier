"""Build a translated test ISO of Macross Triangle Frontier from the original disc.

Usage:
  python tools/build_iso.py <version> [--iso "<original>.iso"] [--tr <insert.json> ...] [--no-hd]
                            [--images] [--work <dir>] [--voice-subs <subs.json> ...] [--voice-placeholder]
                            [--in-place]   (release images: changed files rewritten in their own slot when they
                                            fit, so the xdelta patch stays small; docs/RETRO_TRANS_RELEASES.md)
  e.g. python tools/build_iso.py 0.1.0

Needs (once): the USRDIR files and the decrypted EBOOT extracted as in docs/formats.md,
work/source/dat (tools/muf_archive.py extract), work/source/text (dump_text.py, dump_eboot.py),
and the insert files from tools/corpus_slice.py merge + export:
work/translation/en/insert.json and (campus) insert_campus.json.

Steps (each one is a tool that can also be run on its own):
  1. tools/eboot_insert.py  relocate the English EBOOT text, reserve 4 KB  -> <work>/EBOOT.ins.bin
     (room for the two VWF width tables, 1,552 bytes, and the voice-subtitle hooks, 2 KB)
  2. tools/vwf_build.py     VWF fonts + patches on that EBOOT             -> <work>/vwf/
  2b. tools/voice_subs_patch.py voice-subtitle hooks (only with --voice-subs or
     --voice-placeholder; docs/voice_subtitles.md)                        -> <work>/EBOOT.BIN
  3. tools/insert_text.py   menu CSVs, unit lists, FES scripts, campus .gop tables and
                            .asb event scripts                             -> <work>/overlay/
     (the VWF fonts, data/ and _variants/ of <work>/vwf/, are copied into the same overlay)
  3b. tools/redraw_images.py English redrawn textures (only with --images; docs/image_redraw.md)
  3c. tools/voice_subs_at3.py English line appended to each voice clip    -> <work>/overlay/
     (with --voice-subs; --voice-placeholder writes each clip's id instead, to test the hooks)
  4. tools/muf_archive.py   repack with the overlay (appends what changed) -> <work>/USRDIR/
  5. tools/iso_patch.py     new EBOOT, index and containers               -> work/output/Macross Triangle Frontier (EN v<version>).iso

The EBOOT on the disc is the decrypted PRX (plain ELF). PPSSPP and custom firmware load it as it is.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CONTAINERS = ("macross.idx", "macross.dat", "fileset.dat", "cmp_gop.dat", "cmp_if.dat", "cmp_icon.dat",
              "cmp_charmake.dat", "operator_help.dat", "staffroll.dat")


def run(*args):
    print(">", " ".join(args), flush=True)
    subprocess.run([PY, "-I"] + list(args), cwd=ROOT, check=True)


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        sys.exit(__doc__)
    version = args.pop(0)
    iso = "Macross - Triangle Frontier (Japan).iso"
    tr = []
    vwf_args, work, images = [], None, False
    voice_subs, voice_placeholder, in_place = [], False, False
    while args:
        a = args.pop(0)
        if a == "--iso":
            iso = args.pop(0)
        elif a == "--tr":
            tr.append(args.pop(0))
        elif a == "--no-hd":
            vwf_args.append("--no-hd")
        elif a == "--images":
            images = True
        elif a == "--voice-subs":
            voice_subs.append(args.pop(0))
        elif a == "--voice-placeholder":
            voice_placeholder = True
        elif a == "--work":
            work = args.pop(0)
        elif a == "--in-place":
            in_place = True
        else:
            sys.exit("unknown argument " + a)
    if not tr:
        tr = [p for p in (os.path.join("work", "translation", "en", "insert.json"),
                          os.path.join("work", "translation", "en", "insert_campus.json"))
              if os.path.exists(os.path.join(ROOT, p))]
    b = work or os.path.join("work", "output", "build")
    ins = os.path.join(b, "EBOOT.ins.bin")
    vwf = os.path.join(b, "vwf")
    overlay = os.path.join(b, "overlay")
    usrdir = os.path.join(b, "USRDIR")
    out_iso = os.path.join("work", "output", "Macross Triangle Frontier (EN v%s).iso" % version)
    if os.path.isdir(os.path.join(ROOT, overlay)):
        shutil.rmtree(os.path.join(ROOT, overlay))

    voice = bool(voice_subs or voice_placeholder)
    eboot = os.path.join(vwf, "EBOOT.BIN")
    run("tools/eboot_insert.py", "--reserve", "4096", "--out", ins, *tr)
    run("tools/vwf_build.py", "--eboot", ins, "--out", vwf, *vwf_args)
    if voice:
        eboot = os.path.join(b, "EBOOT.BIN")
        run("tools/voice_subs_patch.py", os.path.join(vwf, "EBOOT.BIN"), eboot, "--area", ins + ".json")
    run("tools/insert_text.py", "--out", overlay, *tr)
    # the VWF fonts: data/extra/*.fnt (RAIC, plain copies) and _variants/gameinit/... (bundle copy)
    for top in ("data", "_variants"):
        for dirpath, _, names in os.walk(os.path.join(ROOT, vwf, top)):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), os.path.join(ROOT, vwf))
                os.makedirs(os.path.dirname(os.path.join(ROOT, overlay, rel)), exist_ok=True)
                shutil.copyfile(os.path.join(dirpath, n), os.path.join(ROOT, overlay, rel))
    if images:
        run("tools/redraw_images.py", "--out", overlay, "--preview", os.path.join(b, "redraw"), "--no-sheets",
            "--version", "v" + version)
    if voice:
        run("tools/voice_subs_at3.py", "--out", overlay, "--widths", os.path.join(vwf, "vwf_widths.json"),
            *(["--placeholder"] if voice_placeholder else voice_subs))
    run("tools/muf_archive.py", "repack", os.path.join("work", "source", "dat"), usrdir,
        "--base", os.path.join("work", "source", "iso"), "--overlay", overlay, *(["--in-place"] if in_place else []))
    run("tools/iso_patch.py", iso, out_iso,
        "PSP_GAME/SYSDIR/EBOOT.BIN=" + eboot,
        *["PSP_GAME/USRDIR/%s=%s" % (f, os.path.join(usrdir, f)) for f in CONTAINERS])
    print("built", out_iso)


if __name__ == "__main__":
    main()
