# Findings: phone JPEGs, AVIF, and two encode profiles

Read on 7 November 2026 from the two JPEG samples in the sample folders beside this repository, from the AVIF files already next to them, from XL Converter's bundled `avifenc` 1.4.2 (SVT-AV1 3.0.2, libaom 3.14.1), and from the Ultra HDR specification page at `https://developer.android.com/media/platform/hdr-image-format`.

The built executable bundles libavif 1.4.2 with SVT-AV1 4.3.0. The measurements below were made with XL Converter's libavif 1.4.2 and SVT-AV1 3.0.2 build. SVT-AV1 4.3.0 maps `-a tune=4` to MS_SSIM all-intra, and its log calls the output Lossy instead of Still Picture.

The program that applies these notes is Image Compactor. This file is the record of what was measured and what was left unmeasured. It is not a submitted article.

## 1. The files

### iQOO Neo 11, 50 MP

Folder `iQOO Neo 11 at 50MP`.

| File | Bytes | Geometry | Pixels | Bits per pixel | Share of the JPEG |
| --- | ---: | --- | ---: | ---: | ---: |
| `IMG_20260919_132935.jpg` | 16,341,161 | 8192×6144 | 50,331,648 | 2.597 | 1 |
| `IMG_20260919_132936.avif` | 3,583,913 | 8192×6144 | same | 0.570 | 0.219 |
| `IMG_20260919_132935.avif` | 2,385,862 | 8192×6144 | same | 0.379 | 0.146 |

Bits per pixel is `bytes × 8 / pixels`.

The person who encoded these AVIFs named the settings. `IMG_20260919_132936.avif` is speed 4, quality 45. `IMG_20260919_132935.avif` is speed 5, quality 35. Both are the same pixel grid as the JPEG.

`ffprobe` on 7 November 2026, stream fields:

- Both AVIFs: `yuv420p`, `color_range=pc`, `color_space=smpte170m`, `color_transfer=unknown`, `color_primaries=unknown`.
- Container name reported by ffprobe: `mov,mp4,m4a,3gp,3g2,mj2`. AVIF uses that ISO base media structure.

8-bit 4:2:0, full range, BT.601 matrix, primaries and transfer left unspecified. The ICC profile in the JPEG is 556 bytes and contains the ASCII `Display P3`. The earlier read of these AVIFs found a `colr` box of type `prof` with an ICC payload of the same general size. `ffprobe` does not print that ICC box in the stream color fields above, which is why the primaries show up as unknown even when an ICC profile is present.

EXIF from the JPEG, read with Pillow:

- Make `vivo`, Model `iQOO Neo11`
- DateTime `2026:09:19 13:29:35`
- ExposureTime `0.000945` s, about 1/1058
- FNumber `1.88`
- FocalLength `5.56` mm, FocalLengthIn35mmFilm `23`
- ISOSpeedRatings `50`
- BrightnessValue `6.28`
- DigitalZoomRatio `1.0`
- Flash `16`
- WhiteBalance `0`
- SceneCaptureType `0`
- ExifVersion `0220`
- ColorSpace `1`

ColorSpace 1 is the EXIF code for sRGB. The ICC description in the same file is Display P3. Those two tags disagree.

The capture log in the JPEG header, in two copies:

- `hw-remosaic: true`
- `module: remosaic` in the first copy, `ModuleId: remosaic` in the second
- `sceneMode: 8192` in the first copy, `sceneMode: RemosaicNight` in the second
- `aec_lux: 144.18834` in the UserComment copy
- `bokeh:1`, `multi-frame` style fields, a touch point

The program prefers the scene name `RemosaicNight` over the number `8192`.

A Qualcomm debug blob (`QTI Debug Metadata`, APP4, many copies, SOS at about 1.58 MB) contains the ASCII `imx766`. There is no `hdrgm:` string, no `GainMap` item, no `21496` string in the header. An `MPF` byte sequence inside the compressed scan is not an MPF marker. This JPEG has one image.

vivo's product page for iQOO Neo11 (`https://www.vivo.com.cn/vivo/param/iqooneo11`, read 7 November 2026) lists a 50 MP LYT700V main camera at f/1.88 and an 8 MP ultrawide at f/2.2. A secondary spec page (jiuphone, same date) adds 1/1.56 inch, 1 µm, 23 mm equivalent, physical focal length 5.56 mm, and calls LYT700V an IMX766 generation part. The EXIF focal length, aperture, and 23 mm equivalent match the main camera, and the file itself contains `imx766`. The frame is 8192×6144, the 50 MP 4:3 readout. A 2×2 bin of that grid would be 4096×3072.

GSMArena rounds the aperture to f/1.9. The EXIF value is 1.88, which matches vivo's page. One retail spec sheet lists a still resolution of 8150×6150. This file is 8192×6144. The file wins.

The model string is `iQOO Neo11`. A different page describes an iQOO Neo11 至尊版. This file does not use that model string.

### Realme GT 8 Pro, tele, 26 MP

Folder `Realme with HP5 sensor`. The folder name is about the sensor the telephoto uses. This JPEG is the telephoto frame. The main camera is a different module.

| File | Bytes | Geometry | Pixel format | Bits per pixel | Share of the JPEG |
| --- | ---: | --- | ---: | ---: | ---: |
| `IMG20260127154721.jpg` | 14,511,165 | 4416×5888 | JPEG | 4.465 | 1 |
| `IMG20260127154719.avif` | 1,443,055 | same | yuv420p | 0.444 | 0.0994 |
| `IMG20260127154720.avif` | 1,426,085 | same | yuv420p | 0.439 | 0.0983 |
| `IMG20260127154721.avif` | 2,015,851 | same | yuv420p10le | 0.620 | 0.1389 |
| `IMG20260127154722.avif` | 2,004,794 | same | yuv420p10le | 0.617 | 0.1382 |

26,001,408 pixels, 26.0 MP. All four AVIFs are full range, matrix `smpte170m`, primaries unknown, transfer unknown. The 10-bit pair is the larger pair. Filename order does not record which slider or which speed produced which file. The 8-bit pair and the 10-bit pair differ in bit depth, and they may also differ in speed and quality. The size gap is about 1.4×. That gap is not a clean measurement of bit depth alone.

The JPEG was described as the same two profiles used on the iQOO pair: speed 5 with quality 35, and speed 4 with quality 45. Four AVIF files exist, two of them 10-bit. Which filename is which slider was not written down. The iQOO pair is the one with a named mapping, and both of those files are 8-bit.

EXIF:

- Make `realme`, Model `realme GT 8 Pro`
- LensModel `realme GT 8 Pro tele camera 65mm f/2.6`
- DateTime `2026:01:27 15:47:20`
- Orientation `1`
- ExposureTime `0.005` s
- FNumber `2.6`
- FocalLength `15.38` mm, FocalLengthIn35mmFilm `67`
- ISOSpeedRatings `400`
- ExposureBias about -1/3 (from the earlier EXIF dump)
- BrightnessValue `8.13`
- DigitalZoomRatio `1.0312`
- ColorSpace `1`
- ICC 548 bytes, ASCII `Display P3`

The maker note begins with JSON. The fields kept for display are `hdrStat=2`, `lightUp=1`, `hdrFusion=0`, `cvtm=720`, `nightFlag=0`. The same JSON has an `iso` field whose text is `8055`. That number is not the exposure ISO. The exposure ISO in EXIF is 400. The program drops the vendor `iso` field. A reader of the form should not take 8055 for the exposure ISO. The vendor codes are not documented here beyond the strings themselves.

GSMArena's GT 8 Pro camera review (page `realme_gt_8_pro-review-2903p5`) states that the telephoto is a 200 MP Samsung ISOCELL HP5 (S5KHP5), 1/1.56 inch, 0.5 µm native photosites binned up to about 2.0 µm, f/2.6, 65 mm, periscope, and that the tele has 12.5 MP, 26 MP, 50 MP, and 200 MP modes. It also says the 26 MP and 12.5 MP modes have a narrower field of view than the 50 MP and 200 MP tele modes. A retail listing (Kimovil) gives the HP5 photosite as 0.80 µm. The JPEG does not contain a photosite pitch, and it does not contain the string `hp5` or `s5khp5`. The pitch stays out of the program. The lens string, the aperture, and the 65 mm lens with a 67 mm equivalent are enough to call this frame the tele.

26 MP is not an integer bin of 200 MP. 200/4 = 50. 200/16 = 12.5. 200/26 is about 7.7. Digital zoom in this file is 1.03. The 26 MP size is the mode the camera chose. It is not a strong extra crop stacked on a 200 MP frame. The review's remark about a narrower field of view is the published description of that mode. This file does not contain a focal-plane crop rectangle to confirm it.

The main camera of that phone is a separate module. Published pages call it about 50 MP and several of them name a Sony IMX906. GSMArena's review says the optical format matches the previous 50 MP imager and that the exact part is less certain. None of that is in this JPEG. This JPEG is the tele.

## 2. What XL Converter actually runs

XL Converter 1.3.x on the `stable` branch calls the bundled `avifenc` for AVIF. The SVT-AV1-PSY case in `core/worker.py` is:

- `-q` set to the quality slider
- `-s` set to the effort slider
- `-j` set to the thread count
- `-c svt`
- `-y 420`
- `-a tune=4`

`tune=4` is the SVT still-picture tune. The help text of this `avifenc` 1.4.2 build lists `tune` as `psnr`, `ssim`, or `iq`, which is the libaom vocabulary. The same binary accepts `-a tune=4` on the SVT path. A previous probe on a 64×48 JPEG with this exact `avifenc.exe` completed with `tune=4` and produced a slightly different file size than the same command without it.

libavif, since SVT-AV1 0.9.0, passes `avifenc -s` through as the SVT `enc_mode`. Speed 4 is preset 4. Speed 5 is preset 5. The window in this program limits the control to 2 through 5 because that is the range worth using on these photos: 2 was visibly cleaner at quality 45 and much slower, and presets above 5 were ruled out.

The quality slider is not a CRF. libavif converts it with integer arithmetic:

```
quantizer = ((100 - quality) * 63 + 50) / 100
```

Checked values:

| Quality slider | Quantizer (CRF) |
| ---: | ---: |
| 100 | 0 |
| 60 (avifenc's own default) | 25 |
| 45 | 35 |
| 35 | 41 |
| 0 | 63 |

On this `avifenc` 1.4.2 binary, quality 45 at preset 4 logs `CRF / 35.00` and `Still Picture`. A 64×48 encode with `--cicp 12/13/6` probes as primaries `smpte432`, transfer `iec61966-2-1`, matrix `smpte170m`, full range.

SVT is in CRF mode here because adaptive quantization is left at 2. Chroma is 4:2:0, matching the XL Converter SVT invocation. A 4:4:4 still would need a different SVT profile and would break the direct JPEG copy described below.

This `avifenc` prints, when it can, that it copied JPEG pixel data without a YUV conversion. A baseline 4:2:0 JPEG then keeps the chroma samples the phone already stored. A second 4:2:0 subsample does not happen on that path. `--sharpyuv` matters after a resize, because the resize is done in RGB and the PNG that follows has to be converted to 4:2:0. The program passes `--sharpyuv` only in that case.

Do not pass `-a avif=1` to this SVT 3.0.2. The option exists from SVT 3.0.0 and had a serious bug (SVT-AV1 issue 2245) that was fixed in 4.0.0. On a one-frame input the encoder may suggest the flag. Leave it off until the binary is SVT 4.0.0 or newer.

There is no ffmpeg fallback. ffmpeg's `libsvtav1` is a different front end and would not carry `tune=4` the same way. If `avifenc.exe` is missing, the program stops and names the file it looked for.

The frozen executable checks its bundled `avifenc` first. A source run checks the environment variable `AVIFENC`, then `C:\Program Files (x86)\XL Converter\_internal\bin\win\libavif\avifenc.exe`, then `C:\Program Files\XL Converter\_internal\bin\win\libavif\avifenc.exe`, then `PATH`.

## 3. The two profiles

Both profiles are SVT-AV1, 4:2:0, full range, `tune=4`. The window labels them High quality and Small copy. It gives the encoders a thread budget that stops one physical core short of the machine's count, and starts every process at below-normal priority.

| | High quality | Small copy |
| --- | --- | --- |
| Purpose | important photos | smaller off-site copies |
| Speed (SVT preset) | 3 | 4 |
| Quality field | 45 | 35 |
| CRF | 35 | 41 |
| Bit depth | 10 | 8 |
| Downscale | off | suggested, from the rules in section 4 |

The form allows any speed from 2 to 5 and any quality from 0 to 100 after a profile is chosen. Switching profile writes that profile's four defaults back into the form.

Bit depth is a deliberate difference from the iQOO sample pair, which is 8-bit in both profiles. 10-bit on High quality is there for gradients at CRF 35. It costs bytes. The Realme folder already shows that a 10-bit pair can land near 2.0 MB where an 8-bit pair of the same frame landed near 1.43 MB, with the caveat in section 1 that those pairs are not a controlled bit-depth test. Set High quality to 8-bit when the comparison that matters is the existing iQOO files.

Preset 3 and preset 4 are the ones to reach for when the phone's output actually holds detail. Preset 2 at quality 45 was described as cleaner still, and slower. Preset 4 at quality 35 is the small copy. The program does not pick the preset from a quality score. It picks from the profile, then from the phone class only for the downscale.

## 4. Downscale arithmetic

Linear scale for a target pixel count:

```
scale = sqrt(target_pixels / source_pixels)
```

Width and height are `round(side * scale)`, then forced to an even number. 4:2:0 needs an even grid. The floor is 2. If both sides land on the original size, the scale is treated as 1 and the JPEG is passed through.

Worked examples for the 8192×6144 iQOO frame (50.332 MP):

| Choice | Scale | Even size | Pixels | Megapixels |
| --- | ---: | --- | ---: | ---: |
| 75% of each side | 0.750 | 6144×4608 | 28,311,552 | 28.31 |
| 80% of each side | 0.800 | 6554×4914 | 32,206,356 | 32.21 |
| Target 24 MP | 0.6905 | 5656×4242 | 23,992,752 | 23.99 |

80% does not stay on a .0 boundary after rounding: 6144×0.8 = 4915.2, which rounds to 4915 and then drops to 4914 because 4:2:0 needs an even height. 75% of this particular frame is exact: 8192×0.75 = 6144 and 6144×0.75 = 4608.

Integer scaling is not required. A 2× decimation of this frame would be 4096×3072, 12.58 MP, which is the quad-bayer bin size and a much harder crop of detail than 24 MP.

Suggested target, small copy profile only:

- Under 40 MP and no remosaic flag: no downscale.
- Otherwise 24 MP.
- Exception: 80 MP or above, and the class is sharp: 48 MP.

Class, before that rule. The window labels Budget High megapixel and Sharp High detail:

- A manual Budget or Sharp choice wins.
- Else if the capture log says hardware remosaic, or the frame is 40 MP or above: budget.
- Else if the frame is from 8 MP through 32 MP: sharp.
- Else unknown, and the suggested downscale stays off.

A remosaic frame marked Sharp by hand still gets the 24 MP suggestion, unless it is also 80 MP or above, in which case the sharp rule yields 48 MP.

On the samples this produces:

- iQOO 50.3 MP, remosaic, Auto: budget. High quality stays 8192×6144. Small copy goes to 5656×4242.
- Realme 26.0 MP, no remosaic flag, Auto: sharp. Both profiles stay 4416×5888.

The 24 MP number is the count that was asked for, as a stand-in for "about the resolution of a normal phone main camera" (the Realme main camera is marketed at 50 MP, and a binned 200 MP HP5 mode at 12.5 MP or the 26 MP tele mode are the frames that already look finished). It is not a measured MTF. Downscaling a remosaiced 50 MP JPEG to 24 MP averages about 1.45 source pixels on each side. A 2×2 quad-bayer cell is 2.0 source pixels on each side and would have been done on the raw mosaic, with the color filters still in the Bayer pattern. Doing it now, after JPEG, only blurs the reconstructed grid. It can still be the right backup size when the reconstructed grid is mostly invented pixels. It does not turn the iQOO sensor into the Realme tele sensor.

The observation that the iQOO frame at 1:1 on a 1080p laptop looks closer to a 540p picture than to a 1080p picture is a viewing note from the person who shot it. No MTF, no slanted-edge, and no paired downscale viewing test was run for this note. The Realme tele frame was described the other way: lower pixel count, and at 1:1 it looks like a 1080p still should. That comparison mixes sensor, lens, pixel pitch, binning, pipeline, and scene. It is not evidence that every 50 MP phone JPEG should become 24 MP, and it is not evidence that 24 MP is a sharpness optimum.

A better phone and a budget phone remain a manual switch because the automatic class is only the remosaic flag plus the pixel count. A 48 MP native full-frame scan and a 48 MP quad-bayer remosaic would take the same branch. The remosaic string is the part that knows the difference, and only phones that write it can be told apart.

## 5. Why the lights go dull

Two different files, two different mechanisms. They were easy to treat as one complaint because both JPEGs look flatter after a normal AVIF encode, and both phone galleries look more vivid.

### 5.1 The iQOO file: primaries and the EXIF tag

There is no gain map in `IMG_20260919_132935.jpg`.

What the file does contain:

- An ICC profile whose description is Display P3 (Apple's 2015 profile text is in the profile, and the device string includes `vivo`).
- EXIF ColorSpace 1, which readers treat as sRGB.
- After XL Converter's encode, an AV1 bitstream whose primaries and transfer `ffprobe` reports as unknown, with matrix BT.601 (`smpte170m`) and full range.

A player that trusts the ICC can paint Display P3 primaries. A player that trusts EXIF ColorSpace, or that trusts the unspecified AV1 color fields and then assumes sRGB or BT.601, paints a smaller gamut. Neon and other saturated lamps sit near the edge of P3 and inside that disagreement. The phone gallery is also an OLED at the phone's own color mode, and iQOO's gallery processing boosts the picture it shot. Those last two are not in the file. Tagging cannot reproduce them.

The tag this program writes, when the checkbox is on and the ICC says Display P3:

```
--cicp 12/13/6 -r full
```

CICP 12 is Display P3 primaries (`smpte432`). CICP 13 is the sRGB transfer (`iec61966-2-1`). CICP 6 is the BT.601 matrix (`smpte170m`), which matches the 4:2:0 JPEG the phone stored. Full range matches `yuvj420p` / `pc`.

The EXIF ColorSpace tag is not rewritten. Rewriting the EXIF IFD to "fix" ColorSpace 1 risks the maker note and still leaves every reader that already cached the old interpretation alone. The color box is the AVIF side of the claim. A gallery that ignores CICP and trusts ColorSpace 1 can still treat the file as sRGB. That limit is real.

XL Converter issue 143 records that, in the absence of an ICC profile, avifenc already writes a CICP the maintainer considers right for sRGB (the numbers discussed there are the sRGB default). These phone JPEGs have an ICC profile. They take the profile path, and the sRGB default is not applied. The explicit `--cicp 12/13/6` is the extra flag.

### 5.2 The Realme file: a gain map the AVIF does not keep

`IMG20260127154721.jpg` is an Ultra HDR JPEG.

Primary XMP (APP1, Adobe XMP Core 5.1.2) uses:

- `http://ns.adobe.com/hdr-gain-map/1.0/` with prefix `hdrgm`
- `http://ns.google.com/photos/1.0/container/`
- `hdrgm:Version="1.0"` in the primary packet
- A directory item `Item:Semantic="GainMap"`, `Item:Mime="image/jpeg"`, `Item:Length="1464522"`

The gain-map parameters are not in that primary packet. They are in the secondary JPEG, which is what the Ultra HDR page requires. Parsed from the first 64 KB of that secondary JPEG:

| Field | Value |
| --- | --- |
| Version | 1.0 |
| GainMapMin | 0 |
| GainMapMax | 2.30045 |
| Gamma | 1 |
| OffsetSDR | 0 |
| OffsetHDR | 0 |
| HDRCapacityMin | 0 |
| HDRCapacityMax | 2.30045 |
| BaseRenditionIsHDR | False |

`BaseRenditionIsHDR` false means the primary image is the SDR rendition and the map lifts it. The same metadata says the offsets are 0. The Ultra HDR page's suggested default offset, used only when the field is absent, is 1/64. Here the field is present and zero. The formula uses zero.

MPF, APP2, file offset 28756. `MPF\0` then a TIFF header four bytes later (Pillow's `mpoffset` rule). Big-endian. Two images:

| Image | Attribute | Size | Offset stored | Absolute file offset |
| --- | ---: | ---: | ---: | ---: |
| Primary | 0x30000 | 13,043,972 | 0 | 0 |
| Gain map | 0 | 1,464,522 | 13,015,212 relative to the TIFF header | 13,043,972 |

The secondary blob starts with `FF D8`. Decoded, it is a 2208×2944 RGB JPEG. That is exactly half of 4416×5888 on each side, one quarter of the pixels. The Ultra HDR page suggests a gain map at one quarter of each side as a typical choice. This phone stored one half of each side.

The three channels are close and not identical. Over 6,500,352 map pixels:

| Channel | Mean | p50 | p90 | p99 | Max | Zeros |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R | 83.94 | 92 | 155 | 183 | 254 | 669,318 |
| G | 82.57 | 91 | 155 | 183 | 254 | 751,794 |
| B | 81.47 | 89 | 155 | 183 | 246 | 784,441 |

Share of pixels with an absolute channel gap above 15: R vs G 2.89%, G vs B 1.31%, R vs B 4.27%. Share where R is at least 20 above both G and B and R is at least 128: 0.08%. The map is mostly a luminance lift. It is not a neon-tint mask. The dull-neon complaint on this file is headroom, the bright parts of the scene being stored only in the map.

No `21496` string appears in the primary header or in the gain-map JPEG. The Android page's v1.1 notes say a current encoder should write Ultra HDR v1 metadata and ISO 21496-1 metadata together, and that a decoder which finds both should prefer ISO 21496-1. This file has the v1 container only. Android 15 is where the platform JPEG path started writing both. The phone build that wrote this file did not put an ISO marker where these scans looked.

### 5.3 The formula, applied to this map

The page defines the decode, for `BaseRenditionIsHDR` false, in floating point. `encoded_recovery` is the 8-bit map sample. With one `GainMapMax` shared by the channels, each channel uses the same constants and its own sample.

```
recovery = encoded_recovery / 255
log_recovery = recovery ^ (1 / gamma)

weight = clamp((log2(max_display_boost) - HDRCapacityMin)
               / (HDRCapacityMax - HDRCapacityMin), 0, 1)

log_boost = GainMapMin * (1 - log_recovery) + GainMapMax * log_recovery

HDR = (SDR + OffsetSDR) * exp2(log_boost * weight) - OffsetHDR
```

`SDR` and `HDR` here are linear. The page is explicit that a linear blend of the map is the wrong display path, because the tonal relationships only hold at the max content boost if the exponent is skipped.

On this file gamma is 1, GainMapMin is 0, both offsets are 0, and HDRCapacityMax equals GainMapMax. Then:

```
log_boost = 2.30045 * (sample / 255)
HDR = SDR * 2 ^ (log_boost * weight)
```

`2 ^ 2.30045 = 4.926`. That is the linear multiplier at map value 255 when the display headroom covers the whole map (`weight = 1`). A display whose SDR-to-HDR white ratio is only `2^1` (twice as bright) gets `weight = 1 / 2.30045 ≈ 0.435`, and every pixel's boost is reduced by that factor inside the exponent.

Per channel, weight 1, the stored samples convert as:

| Sample | recovery | log2 boost | Linear multiplier |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 0 | 1.000 |
| 89 (B median) | 0.349 | 0.803 | 1.745 |
| 92 (R median) | 0.361 | 0.830 | 1.778 |
| 155 (p90, all channels) | 0.608 | 1.398 | 2.636 |
| 183 (p99, all channels) | 0.718 | 1.651 | 3.140 |
| 254 (R and G max) | 0.996 | 2.291 | 4.895 |
| 255 | 1 | 2.300 | 4.926 |

About 10% of the map pixels are zero on a given channel: those pixels stay at the SDR base even in the phone gallery. The upper tail does not. At the 90th percentile the linear highlight is 2.64 times the SDR base, on a display that can spend the full headroom. An AVIF of the primary JPEG alone keeps the SDR base. On an HDR screen that is the duller picture. On an SDR screen the primary was always the intended picture, which is why the same AVIF can look acceptable on a laptop and wrong in the phone gallery.

The program reports the map and then encodes the primary. It passes `--ignore-xmp` when a map is present. The AVIF then does not claim a gain map it does not contain. Applying the map into a 10-bit PQ or HLG picture, or embedding an ISO 21496-1 gain map in the AVIF, is a different project. Doing it without a check in the phone gallery would change the colors on a guess. The metadata above is enough to compute the intended multiplier. It is not a rendered HDR frame.

The iQOO dullness and the Realme dullness meet only at the end of the sentence "the AVIF looks flatter on the phone." The fixes are different. CICP tagging addresses the iQOO file. It does nothing for the Realme highlights that live in the gain map. A gain-map render would address the Realme file. It would not invent the gallery's extra vividness on the iQOO file, which has no map.

## 6. Direct copy, resize, and metadata

No downscale: a JPEG is handed to `avifenc` unchanged. Any other format is decoded and written to a PNG first. EXIF travels with the JPEG unless a flag strips it. XMP travels with a direct JPEG copy, and a gain map adds `--ignore-xmp`. The PNG path does not carry the original XMP. `DateTime` and `DateTimeOriginal` stay in that EXIF block.

Downscale: Pillow applies EXIF orientation, converts to RGB, resizes with Lanczos to the even size, and writes a PNG that carries the same ICC bytes. An EXIF sidecar is written when the source carries EXIF, with Orientation set to 1, because the pixels are already rotated. `avifenc` then gets `--exif` for that sidecar (which implies `--ignore-exif` on the PNG, and the PNG has none) and `--sharpyuv`. The sidecar is Pillow's EXIF, not a byte copy of the JPEG's APP1. Capture dates that Pillow read are written back. A maker note Pillow does not round-trip can be absent on this path.

After a successful encode, the AVIF's accessed time and modified time are copied from the source. A sort by Date modified follows the source. The AVIF's created time is the encode time. Windows does not let `os.utime` set that.

The encoder command is one list, not a shell string. A failed encode leaves no new output and no partial file. Stop during a batch kills the running `avifenc` processes and leaves the sources in place. Files already finished in that batch stay finished.

Output names use the source's stem. With Overwrite existing AVIFs off, `IMG_20260919_132935.jpg` with an existing `IMG_20260919_132935.avif` produces `IMG_20260919_132935-2.avif`. With it on, a successful encode replaces the existing name. A failed encode leaves the old file in place. The samples in this folder are on the list of names to avoid when the toggle is off.

## 7. What a quality number can and cannot decide

The request was for a tool that looks at a photo and decides whether it needs a downscale, a quality around 40, or both. The reliable signal in these two files is metadata: remosaic, pixel count, lens, ICC versus EXIF, gain map. A no-reference score was not run. Running one would not replace that metadata.

### 7.1 Full reference

PSNR, in decibels:

```
PSNR = 10 * log10(MAX^2 / MSE)
```

`MAX` is the peak code value (255 for 8-bit). MSE is the mean squared error against a reference picture. SSIM (Wang, Bovik, Sheikh, and Simoncelli, IEEE Transactions on Image Processing, vol. 13, no. 4, pp. 600-612, April 2004, DOI `10.1109/TIP.2003.819861`) compares local luminance, contrast, and structure between a reference and a distorted image. Both need the reference.

The reference for a phone JPEG is the raw mosaic, or at least the linear render before the phone's JPEG. These files are the JPEG. Scoring the AVIF against the JPEG measures how faithfully the AVIF kept the JPEG, including the JPEG's own damage. It does not measure whether the 50 MP grid deserved to exist. A high SSIM at 8192×6144 can mean "the invented pixels were preserved."

A useful full-reference number for the profile question would be SSIM or PSNR of the AVIF against the JPEG after both are viewed at the same display size, plus a second number at 1:1 on a crop the photographer cares about. That still grades fidelity to the JPEG. It does not grade the camera.

### 7.2 No reference

BRISQUE (Mittal, Moorthy, and Bovik, IEEE Transactions on Image Processing, vol. 21, no. 12, pp. 4695-4708, December 2012, DOI `10.1109/TIP.2012.2214050`) builds a feature vector from mean-subtracted contrast-normalized luminance. Pairwise products of neighboring coefficients are fit with an asymmetric generalized Gaussian. The published model uses 36 features and a support-vector regression trained on scored images. The score is only as relevant as that training set.

A dark, detailed frame from a good sensor scores worse than a bright, flat frame from a poor one if the training set treats noise and darkness as damage. Nothing in the 36 features says "quad-bayer remosaic" or "gain map present." MUSIQ, CLIP-IQA, NIQE, LPIPS, SSIMULACRA2, and Butteraugli are the other names that come up for this job. They were not run, and the papers were not re-read for this note. Citing a score from an unrun model would be a fiction. The metadata already classifies the two samples without them.

A preview statistic on a thumbnail (a Laplacian variance, a share of pixels near the P3 boundary) can be shown as a number about that thumbnail. It is not a phone class. The program does not show one. Header inspection is what runs when a file is selected. A 50 MP JPEG does not have to be fully decoded to fill the form. The Realme gain map was decoded once, offline, to fill section 5. The window does not decode it. It reads the XMP fields.

### 7.3 The decision the program actually makes

1. Read the header: size, ICC name, EXIF, remosaic log, a few sensor strings, MPF gain map, a short list of maker-note keys.
2. Class: manual choice, else remosaic or at least 40 MP, else 8-32 MP, else unknown.
3. Profile defaults for speed, quality, bit depth, and whether a downscale is even considered.
4. If a downscale is requested, compute the even size in section 4.
5. If the ICC says Display P3 and the checkbox is on, add `--cicp 12/13/6`.
6. If a gain map exists, say so, keep the SDR base, drop the XMP.

Step 2 is a rule of thumb with the numbers from the request (50 MP toward 24 MP, 108 MP and 200 MP toward 48 MP when the class is sharp, toward 24 MP when it is budget). It is not a fitted model. Two phones are not a training set.

## 8. A second article: what would be new

The university asks for a second article. The bar that makes an article worth sending is a measurement someone can repeat, aimed at a hole the existing papers leave open. SSIM and BRISQUE already occupy "score a picture against a reference" and "score a picture with a trained natural-scene model." Another tabulation of those scores on a private folder of phone photos does not clear the bar.

The hole these two files actually point at is narrower:

Phone JPEGs arrive after the camera pipeline. The pipeline's choices are written beside the pixels: a remosaic flag, a pixel count that may be a bin or a crop or a full quad-bayer readout, an ICC profile that contradicts EXIF ColorSpace, and sometimes an Ultra HDR gain map whose linear headroom is on the order of 5× while the primary image looks finished in an SDR viewer. A still-AVIF encoder that only sees width, height, and a quality slider will keep the wrong pixels and drop the headroom. The routing decision is a function of the container, and the color error is a function of which box the player trusts.

That can be a paper if the following exist. They do not exist yet.

1. A set of phone JPEGs, more than two, with the container fields recorded the way section 1 records them. The set has to include remosaic readouts at 50, 108, and 200 MP and finished frames around 12-26 MP, from more than one vendor, plus a few Ultra HDR files whose gain-map metadata parses. Publish the field list and the byte offsets, not the private photos, if the photos cannot be shared. A public set is better.

2. An encode grid on that set: SVT presets 2, 3, 4, and 5, quality sliders 35 and 45, 8-bit and 10-bit, full resolution and the 24 MP or 48 MP target, with and without `--cicp 12/13/6`. Same `avifenc` version on every cell. Write the command line into the table.

3. Two viewing conditions, scored by people: an SDR laptop at 1:1 and at fit-to-window, and the source phone's gallery. An unrun no-reference model does not fill this cell. The questions to score separately are detail and highlight color. Mixing them into one MOS hides the Realme failure mode, which is color and headroom, inside a detail score the 26 MP frame would win anyway.

4. For every Ultra HDR file, a numeric companion that does not need a viewer: the distribution of `2 ^ log_boost` under weight 1, computed from the gain map the way section 5.3 does for one file. Report the median, the 90th percentile, and the max. That number is the linear light the AVIF threw away. On this one Realme file the max is 4.90 on the red and green channels (sample 254) and the defined ceiling is 4.93. One file is an example. A table across phones is a result.

5. A short error analysis of the tag fight: the same pixels decoded under ICC Display P3 and under EXIF-sRGB, reported as a color difference on the saturated pixels only. The iQOO file is the motivating case. The difference is zero on gray and large on the lamps. An average over the whole frame will hide it.

A journal that published SSIM or BRISQUE (IEEE Transactions on Image Processing) is the wrong desk for a note that does not yet have items 1, 2, and 3. Those papers became the reference because the model and the data were both in the paper. A measurement paper with a repeatable encode grid and a small viewing test fits a multimedia-quality venue. QoMEX is the conference that already sits on that topic. Signal Processing: Image Communication is the kind of journal that publishes encoder comparisons. IEEE Consumer Electronics Magazine is the kind of magazine that will take a shorter piece if the picture story is concrete. This paragraph names the neighborhood. It is not a scope check against a current call for papers, and it is not an acceptance estimate.

What this folder can already contribute to that paper, and no more:

- The parse of two real containers, including the MPF base (TIFF header, not the start of the file, for a non-zero offset).
- The quality-slider arithmetic and the CICP triple, checked against `ffprobe` on a tiny encode in the unit tests (`smpte432`, `iec61966-2-1`, `smpte170m`, `pc`).
- One fully worked gain map: dimensions, per-channel histogram, and the linear multipliers.
- A negative result: no-reference IQA is the wrong instrument for the routing decision, for the reason in section 7.2.

What it cannot contribute yet: a preference rate, a confidence interval, a claim that 24 MP is optimal, a claim that quality 45 is optimal, a claim that CICP tagging fixes the iQOO gallery. The tagging is the right metadata. Whether a given gallery honors it is an experiment, and it has to be run on the phone.

ISO 21496-1 is the published gain-map standard the Android page tells new encoders to write alongside Ultra HDR v1. This note does not summarize that standard. The standard was not opened. A paper that embeds gain maps in AVIF has to read it, and has to compare a v1-only JPEG such as this Realme file with a file that carries both metadata blocks.

## 9. A phone app, later

A paid or freemium phone app is a product idea on top of the same facts. This folder does not contain a spec for it.

The part a phone gallery already does, and a desktop AVIF encoder does not, is the gain map. An app that produced an AVIF the same gallery will show with the highlights intact is the feature with a reason to exist. That means either writing a gain map the gallery understands inside the AVIF, or baking a display-referred rendition and saying so on the screen. Baking at weight 1 clips any phone whose panel cannot reach 4.93× the SDR white. The Ultra HDR weight term is what makes the picture scale with the panel. An app that bakes at weight 1 and calls the result "the HDR photo" has picked one panel and frozen it.

Encoding AVIF on a phone is the other cost. AV1 decode is widespread. AV1 encode at SVT preset 4 on a 50 MP frame is a desktop-sized job. A phone app that wants the small copy profile (preset 4, quality 35, optional 24 MP) can plausibly run it on device, slowly, or on a desktop the phone already syncs to. The high quality profile at preset 3 is the batch that belongs on the charger and the laptop. That split matches the two profiles already in the window. It is not a price list.

The color tag has to be tested in the target gallery before the app promises vivid lamps. Section 5 is the reason.

Nothing in the current program is a mobile build. There is no account system, no store listing, and no encoder other than the local `avifenc`.

## 10. Limits of this note

- Two scenes, one frame each. No claim about a third phone.
- The iQOO AVIF filenames are tied to sliders by the photographer. The Realme AVIF filenames are not.
- No MTF, no paired viewing scores, no BRISQUE or SSIM numbers.
- The gain-map histogram is one file, decoded with Pillow, per channel.
- Vendor maker-note integers are quoted and not translated.
- Sensor identity for the iQOO file is the string `imx766` plus vivo's LYT700V spec page. Sensor identity for the Realme file is the lens string plus the review pages, not a string in the JPEG.
- `tune=4` is passed because that is XL Converter's SVT still-picture setting on this 3.0.2 build. The bundled SVT-AV1 4.3.0 maps the same argument to MS_SSIM all-intra.
- With Overwrite existing AVIFs off, the program does not replace a sample AVIF. It never deletes a source file.

## Sources opened for this note

- Android Ultra HDR image format, `https://developer.android.com/media/platform/hdr-image-format`, fetched 7 November 2026. Decode formulas, metadata table, MPF requirement, v1.1 changelog about ISO 21496-1. The gain-map math in section 5.3 is that page, with this file's numbers substituted.
- vivo iQOO Neo11 specifications, `https://www.vivo.com.cn/vivo/param/iqooneo11`, fetched 7 November 2026. 50 MP LYT700V, f/1.88, 8 MP ultrawide f/2.2.
- Wang, Bovik, Sheikh, Simoncelli, "Image quality assessment: from error visibility to structural similarity", IEEE Trans. Image Process. 13(4):600-612, 2004. DOI `10.1109/TIP.2003.819861`.
- Mittal, Moorthy, Bovik, "No-Reference Image Quality Assessment in the Spatial Domain", IEEE Trans. Image Process. 21(12):4695-4708, 2012. DOI `10.1109/TIP.2012.2214050`.
- XL Converter `core/worker.py` on the `stable` branch, SVT AVIF arguments, read for the command in section 2.
- libavif `svtQualityToQuantizer` and the SVT speed pass-through, as implemented by the formula in section 2 and checked by `quality_to_crf` in the tests.
- GSMArena, Realme GT 8 Pro camera review, for the HP5 tele modes including a 26 MP mode. Kimovil's HP5 photosite pitch disagrees with that review. The pitch is unused.
- This folder's bytes, EXIF, XMP, MPF, and `ffprobe` output, collected 7 November 2026.

Secondary pages (jiuphone on the LYT700V / IMX766 identification, retail spec sheets) were used only where section 1 says so, and they lose to the file when they disagree with it.
