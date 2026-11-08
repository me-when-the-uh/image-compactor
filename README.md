# Image Compactor

## This is very much a work in progress!

For when [Trash-Compactor](https://github.com/me-when-the-uh/trash-compactor) isn't enough...

Image Compactor's goal is to convert photos to a very efficient AVIF format that is gaining popularity nowadays. It accepts bulky JPEG, PNG, WebP, TIFF, BMP and GIF files.

This program performs a lossy compression for archival/backups. The reasoning is that most modern phones under $500 are unable to shoot actual good quality photos - you would end up with bulky 50MP+ photos that are nowhere near the expected quality, which means that the 15-20MB of space taken up by each large photo is ~80% wasted.

AVIF is able to squeeze the space taken up by photos and images **by 2x-8x.** The larger the photo, the better it gets compressed.

As of right now, the only issue serious enough to get highlighted is that HDR data gets lost. You'll be stuck with SDR photos, and the colours would look a little less vivid. But for archival/backup purposes, it's not a big deal. It's always better to have something than not have anything to show for at all.

---

## Run

The built executable is `dist\image-compactor.exe`. It carries its own `avifenc` build and does not need XL Converter.

For a source run on Windows, use Python 3.11 or newer. Run these commands from the folder that contains this repository:

```
py -m venv image_compactor\.venv
image_compactor\.venv\Scripts\python -m pip install -r image_compactor\requirements.txt
image_compactor\.venv\Scripts\python -m image_compactor
```

Use `image_compactor\.venv\Scripts\pythonw.exe -m image_compactor` to start without a console window.

A source run looks for `avifenc.exe` in `C:\Program Files (x86)\XL Converter\_internal\bin\win\libavif\`, then in `C:\Program Files\XL Converter\...`, then on `PATH`. Set the `AVIFENC` environment variable to point at a different build, or choose `avifenc.exe` with Browse on the Settings page. The built executable uses its bundled encoder first.

## Build

From the repository root:

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

A cold build needs Python 3.11+ (64-bit), CMake, Git, Visual Studio 2022 Build Tools with the MSVC C++ workload, and internet access. A source encoder build downloads NASM 2.16.03, libavif 1.4.2, and SVT-AV1 4.3.0 and builds a static `avifenc` with JPEG and PNG input plus `--sharpyuv`. A rebuild packages `dist\image-compactor.exe` as one file. It runs the unit tests and the frozen checks. The executable bundles the encoder and its VC runtime. XL Converter is not used by the frozen app.

The executable is reused when `dist\image-compactor.exe` is newer than the source, build files, and cached encoder. The script prints that the build is up to date and exits without rebuilding or verifying. Pass `-Force` to rebuild the executable. Pass `-ForceEncoder` to rebuild the encoder and then the executable.

The encoder is reused from `build\encoder` when `avifenc.exe` is already there. The source build is skipped. If it is missing, the script asks for confirmation before starting the long source build, which can take 10 to 40 minutes. Pass `-SkipEncoderBuild` to refuse a source build, or `-SkipVerify` to skip the frozen checks on a rebuild. The build logs are in `%TEMP%\ic-*.log`.

The bundled SVT-AV1 4.3.0 build treats the existing `-a tune=4` argument as its MS_SSIM all-intra tune. The source measurements in [docs/findings.md](docs/findings.md) were made with XL Converter's SVT 3.0.2 build, where the same argument was the still-picture setting.

Save to has two choices. Same folder writes beside each source. Someplace else uses the folder shown below it. Overwrite existing AVIFs replaces a matching AVIF only after the new encode succeeds. With it off, an existing `.avif` is left alone and the new file is `name.avif`, or `name-2.avif` when that name is taken.

The capture dates inside EXIF (`DateTime`, `DateTimeOriginal`) are copied into the AVIF. The AVIF's Date modified is set from the source's Date modified. A folder sorted by that column stays in the same order. Date created on the new file is the time of the encode. A resize rebuilds the EXIF block with orientation already applied. The capture dates are still in that block. A gain-map photo drops its XMP and keeps the EXIF.

## Window

The Convert page holds the Photos list, the selected photo's facts, the Activity log, the progress bar, and the green Convert to AVIF button. The Settings page holds the profile and encoder controls, the overwrite toggle, and the encoder field. The About page shows the version, supported formats, and the encoder path.

The Photos table shows ready, queued, inspecting, converting, done, failed, skipped, and stopped. A finished row shows the output size and the percentage of the source size it now takes. The Activity log shows the same ratio, the batch summary, and any error text. The progress bar turns green when a batch finishes and grey when it is stopped.

Drag and drop uses `tkinterdnd2`. Without that package the window still runs, and Add files and Add folder remain available.

## Input

JPEG, PNG, WebP, TIFF, BMP and GIF are accepted. EXIF orientation is applied before a resize. PNG and WebP alpha is kept. Animated GIF and WebP use the first frame. HEIC, camera raw, and other formats Pillow cannot decode are rejected with a message in the activity log.

## Profiles

The SVT preset is the SVT-AV1 effort level. The window allows 2 through 5. Quality is the same 0-100 field XL Converter passes to `avifenc -q`. The field next to it shows the CRF it becomes. Quality 45 is CRF 35. Quality 35 is CRF 41.

| | High quality | Small copy |
| --- | --- | --- |
| SVT preset | 3 | 4 |
| Quality | 45 | 35 |
| Bit depth | 10 | 8 |
| Resolution | the source's size | suggested, for large and remosaic photos |

Switching profile fills those four controls, and they can be edited afterwards. High quality is 10-bit, which spends bytes on smooth gradients, and 8-bit is there when the smaller file matters more.

## Source class

Auto detect, High megapixel, and High detail are on the form. Auto detect reads the source:

- A hardware-remosaic tag, or a photo at 40 MP or above, is treated as a high-megapixel frame.
- A photo from 8 MP through 32 MP, with no remosaic tag, is treated as a high-detail frame.
- Anything else stays unknown. The suggested scale stays off for files under 40 MP without a remosaic tag.

On Small copy, with resolution set to Suggested:

- A high-megapixel or remosaic photo is resized toward 24 MP.
- A high-detail photo at 80 MP or above is resized toward 48 MP.
- A high-detail photo already under 40 MP, with no remosaic tag, keeps its pixel count.

Custom scale is a separate choice. 75% of each side keeps about 56% of the pixels. 80% keeps about 64%. Both are rounded to even width and height.

A 4:3 frame at 8192 by 6144, the usual 50 MP readout, resized toward 24 MP becomes 5656 by 4242, about 69% of each side. That is an even scale of the finished JPEG, not a 2 by 2 bin of the sensor, and it does not grow the photosites.

## Colour

When the ICC profile says Display P3 and the checkbox is on, the AVIF is tagged primaries 12, transfer 13, matrix 6, full range, and the profile stays in the file. EXIF ColorSpace is left as the camera wrote it. A gain map is named in the log with the values the file stored, and the AVIF is the base image: the map is not applied, its XMP is dropped, and the file does not claim to contain a map.

## Limitations

Saturated lights go dull when the gallery was showing a range or a colour the AVIF never received.

Phone JPEGs often ship a Display P3 profile with EXIF ColorSpace set to 1, which suggests using sRGB. Some colours reside in the DCI-P3 range that sRGB does not cover, and a viewer that trusts the EXIF tag (and ignores the AVIF colour box) displays a photo with a duller colour gamut.

AVIF encoder disregards gain maps that contain extra colour brightness data. Samsung, Pixel, OPPO, Realme and OnePlus cameras may store Ultra HDR as an ordinary base with a map that their gallery apps apply on an HDR screen, and iPhones store the same kind of map in the HEIC format. `avifenc` cannot write a gain map, resulting in duller colours.

Vivo and iQOO phones seem to keep the HDR data elsewhere, and Samsung's Gallery app may add a display tone map on top of a file that already has a gain map.

JPEG XL would not close this. Galleries that show AVIF and an Ultra HDR JPEG do not apply a JPEG XL gain map, and a PQ JPEG XL would bake one panel's headroom into the pixels. Follow-ups are in [TODO.md](TODO.md).

## Checks

From the folder that contains this repository:

```
image_compactor\.venv\Scripts\python -m unittest discover -s image_compactor\tests -t .
```

The tests that use the sample photos skip when those folders are absent. The encoder checks use small generated images. Drag and drop needs `tkinterdnd2`. The rest of the window runs without it.
