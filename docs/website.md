# Website and search maintenance

[简体中文](website.zh-CN.md) · [Local development](development.md)

The public website is [Harmattan QEMU](https://yzune.github.io/harmattan-qemu/), with a [Chinese edition](https://yzune.github.io/harmattan-qemu/zh/). The [English video page](https://yzune.github.io/harmattan-qemu/watch/) and [Chinese video page](https://yzune.github.io/harmattan-qemu/zh/watch/) embed the same published [YouTube trailer](https://www.youtube.com/watch?v=GArapJ3rOIo). Keep these URLs stable when updating the project.

## Edit and preview

The four pages are plain HTML: [English home](index.html), [Chinese home](zh/index.html), [English video](watch/index.html) and [Chinese video](zh/watch/index.html). They share [site.css](assets/site.css) and the small, deferred [cobble.js](assets/cobble.js) geometry enhancement. There is no package installation or JavaScript build. Font names use the visitor's installed fonts; no font files or standalone N9 artwork are distributed. The home pages use the existing reviewed screenshots and a CSS-drawn frame.

### Local preview

From the repository root, serve the site at its production path:

```sh
mkdir -p artifacts/site-preview
ln -s ../../docs artifacts/site-preview/harmattan-qemu
python3 -m http.server 8765 --bind 127.0.0.1 --directory artifacts/site-preview
```

Create the symlink only once; if it exists, check its target instead of replacing it. Open `http://127.0.0.1:8765/harmattan-qemu/`. Navigation and language links also work locally; canonical and social metadata retain the production URLs.

Check both languages on desktop and a narrow viewport, visible keyboard focus, local assets, metadata and [sitemap.xml](sitemap.xml). Verify the real video embed after publication. Then use the exact-path staging, publication check and PR workflow in [local development](development.md). No emulator rebuild is required for website-only changes.

## Deployment

GitHub Pages serves the `main` branch's `/docs` directory. The empty `.nojekyll` file keeps the HTML and CSS unchanged. In repository **Settings → Pages**, use **Deploy from a branch**, `main`, `/docs`. A merged change triggers deployment; check the Pages deployment and live URLs before announcing it. The repository homepage should point to the website.

Update English and Chinese copy together. Keep each page's title, description, canonical URL, reciprocal `hreflang` links and social preview consistent with its content. When replacing the video, update both watch pages, their `VideoObject` JSON-LD, thumbnail URL, duration, real upload date, transcript, README links and YouTube description. Do not label edited 4K/60 fps video as a measurement of emulator performance.

## Google Search Console

1. In [Search Console](https://search.google.com/search-console/), add the URL-prefix property `https://yzune.github.io/harmattan-qemu/` using the maintainer's Google account.
2. Choose HTML-tag verification and place the exact provided `google-site-verification` meta tag in `docs/index.html`. Publish it before clicking Verify. Retain the tag while the property is in use. Never substitute a guessed token or another person's account.
3. Submit `https://yzune.github.io/harmattan-qemu/sitemap.xml`. Inspect the home and video URLs and, if eligible, request indexing once. Check Page indexing, Video indexing and Performance reports as data becomes available.

The project does not control `github.com` or the `youtube.com` domain. A GitHub Pages URL-prefix property covers this website only. A `robots.txt` inside this project path would not control the host's root crawling policy, so none is supplied.

Google decides whether and when to index a page. A sitemap, verification, structured data or crawl request does not guarantee inclusion, a video result or a ranking. Monitor actual reports instead of repeatedly submitting URLs. See Google's [crawl request guidance](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl), [video guidelines](https://developers.google.com/search/docs/appearance/video) and [multilingual site guidance](https://developers.google.com/search/docs/specialty/international/managing-multi-regional-sites).

## GitHub and YouTube

Use accurate terms such as Nokia N9, MeeGo Harmattan, QEMU, Apple Silicon and software preservation in natural descriptions. Keep the GitHub About description and Topics aligned with the actual runtime scope. README, website and video description should link to the project, preview downloads and guest preparation guide.

For YouTube, maintain a clear title and opening description, a representative thumbnail and accurate English captions. Keep existing source and artwork credits and the music-production disclosure. Tags are secondary to title, thumbnail and description; see [YouTube's guidance](https://support.google.com/youtube/answer/146402). Clickable external description links can require channel advanced-feature access, which is separate from phone verification for custom thumbnails. Do not promise working links until verified on the public watch page.
