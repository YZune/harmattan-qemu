# 网站与搜索维护

[English](website.md) · [本地开发管理](development.zh-CN.md)

项目主页为 [Harmattan QEMU](https://yzune.github.io/harmattan-qemu/)，另有[中文版](https://yzune.github.io/harmattan-qemu/zh/)。[英文视频页](https://yzune.github.io/harmattan-qemu/watch/)和[中文视频页](https://yzune.github.io/harmattan-qemu/zh/watch/)嵌入同一条已发布的 [YouTube 宣传片](https://www.youtube.com/watch?v=GArapJ3rOIo)。后续更新尽量保持这些网址稳定。

## 修改与预览

四个页面均为静态 HTML：[英文首页](index.html)、[中文首页](zh/index.html)、[英文视频页](watch/index.html)、[中文视频页](zh/watch/index.html)，共用 [site.css](assets/site.css)。无需安装依赖或运行 JavaScript 构建。字体名称调用访客本机已有字体，不分发字体文件或独立 N9 机身素材。首页使用已有的审核截图与 CSS 绘制的外框。

在仓库根目录运行，以生产环境的项目路径预览：

```sh
mkdir -p artifacts/site-preview
ln -s ../../docs artifacts/site-preview/harmattan-qemu
python3 -m http.server 8765 --bind 127.0.0.1 --directory artifacts/site-preview
```

符号链接只需创建一次；已存在时先检查目标，不要覆盖。打开 `http://127.0.0.1:8765/harmattan-qemu/`。导航与语言切换在本地预览中也可使用；canonical 和社交元数据保留正式网址。

检查两种语言在桌面与窄屏下的布局、可见键盘焦点、本地素材、页面元数据及 [sitemap.xml](sitemap.xml)，发布后验证真实视频嵌入。按[本地开发管理](development.zh-CN.md)精确暂存文件、执行发布检查并提交 PR。只修改网站时无需重建模拟器。

## 部署

GitHub Pages 从 `main` 分支的 `/docs` 目录发布，空的 `.nojekyll` 文件让 HTML 与 CSS 原样提供。在仓库 **Settings → Pages** 中选择 **Deploy from a branch**、`main`、`/docs`。合并修改后触发部署；对外宣布前检查部署结果与在线网址。仓库主页字段应指向网站。

中英文文案同步维护。每个页面的标题、摘要、canonical、双向 `hreflang` 与社交预览须对应真实内容。更换视频时，同时更新两种语言的视频页、其中的 `VideoObject` JSON-LD、缩略图网址、时长、真实上传日期、文字内容、README 链接及 YouTube 说明。不要把成片的 4K/60 fps 规格当作模拟器性能实测。

## Google Search Console

1. 使用维护者的 Google 账号进入 [Search Console](https://search.google.com/search-console/)，添加网址前缀资源 `https://yzune.github.io/harmattan-qemu/`。
2. 选择 HTML 标记验证，将实际提供的 `google-site-verification` meta 标签放入 `docs/index.html`，发布后再点击验证。使用该资源期间保留标签。不要猜测令牌，也不要使用他人账号。
3. 提交 `https://yzune.github.io/harmattan-qemu/sitemap.xml`。检查首页与视频页的网址，符合条件时请求一次编入索引；数据生成后查看网页索引、视频索引和效果报告。

本项目不控制 `github.com` 或 `youtube.com` 域名。GitHub Pages 的网址前缀资源只覆盖本网站。项目路径里的 `robots.txt` 无法控制宿主根目录的抓取规则，因此未添加此文件。

是否收录、何时收录由 Google 决定。站点地图、验证、结构化数据和抓取请求均不保证收录、视频结果或排名。应观察实际报告，避免反复提交网址。参见 Google 的[请求抓取说明](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl)、[视频指南](https://developers.google.com/search/docs/appearance/video)与[多语言网站指南](https://developers.google.com/search/docs/specialty/international/managing-multi-regional-sites)。

## GitHub 与 YouTube

在自然描述中使用 Nokia N9、MeeGo Harmattan、QEMU、Apple Silicon、软件保存等准确词语。GitHub About 简介和 Topics 应与真实运行范围一致。README、网站与视频说明应互相链接，并提供预览版下载及资源准备入口。

YouTube 维护清晰的标题与说明开头、真实封面和准确英文字幕，保留来源、素材致谢及配乐制作披露。标签的重要性低于标题、封面和说明，参见 [YouTube 官方建议](https://support.google.com/youtube/answer/146402)。说明里的可点击外部链接可能需要频道高级功能权限；这与上传自定义封面所需的手机验证不同，须在公开观看页验证后才能确认链接可点击。
