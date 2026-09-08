# 可选机身素材

[English](README.md)

本目录不分发 PNG 或 PSD。默认运行及原生几何测试均不依赖素材。

可选集成基于 Liwen Guo / Livven 的 Nokia N9 PSD（2011）开发，记录中的原作者页面为 [Nokia N9 PSD](http://livven.me/psds/nokia-n9-psd/)。其使用条款独立于本仓库代码许可，尚未确认采用开源素材许可；使用或再分发前应确认权限。

已取得权限和原 PSD 的用户，可使用 `export-n9-livven.py` 在本地导出。该可选工具需要独立 Python 环境中的 `psd-tools==1.19.0`、Pillow 和 NumPy，输出符合开孔几何的 1240×2320 PNG。用法见 `--help`；不要提交生成的图像。

将获准使用的本地结果放到 `ports/qemu-n00/skins/n9-black-livven.png`，重新构建 `--cocoa-interaction`，再为启动器显式设置 `HARMATTAN_UI_SKIN=black`。构建会将本署名说明与提供的图像一同放入应用包。默认值为 `HARMATTAN_UI_SKIN=off`。

视图代码标记为 MIT，不代表素材采用 MIT；合成测试图也不验证原 PSD 的渲染或真实性。

`HARMATTAN_UI_SKIN=frame` 选择项目原创代码绘制的外框，是预编译发行版的默认选项，不需要 PNG 或 PSD。

代码外框采用扁平石墨灰机身、内嵌黑色玻璃和简化的硬件细节。机身与显示区域比例依据 N9 公开规格推导，其余尺寸明确作为项目设计取值，见[几何依据与来源](frame-geometry.zh-CN.md)。布局独立于可选素材映射，保留完整客体画面、玻璃边缘手势和下方侧键动作。外框改动需要重新构建 Cocoa 应用后才能看到，现有二进制仍使用此前的绘制效果。

全新交互构建还将下方侧键接入[原版锁屏](../../../docs/lockscreen.zh-CN.md)。原图保持不变，点击区域由宿主视图处理，同样支持代码绘制的 `frame` 外壳。
