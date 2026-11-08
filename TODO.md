# TODO

- [ ] Carry the gain map into the AVIF. Samsung, Pixel, OPPO, Realme and OnePlus cameras may store Ultra HDR as a base with a map, and iPhones store the same kind of map in HEIC. `avifenc` cannot write a gain map. The job needs a libavif that reads the map the camera wrote and emits an ISO 21496-1 item, then a check in that vendor's gallery.
- [ ] On Vivo, iQOO, and Samsung Gallery, where the HDR data is not the gain map in the file, check whether a Display P3 tag changes what the gallery shows.
- [ ] Baking the map into the pixels waits on a chosen screen headroom. Full headroom fits one panel.
- [ ] Keep JPEG XL out of this tool. A gallery that shows AVIF and an Ultra HDR JPEG is unlikely to apply a JPEG XL gain map.
