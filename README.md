# 小满盯盘器 v0.1

手机优先的 A 股盯盘原型。

## 功能
- 默认自选：多氟多、日盈电子、东山精密、588950
- 公开行情读取
- MA5 / MA10 / MA20
- 自定义关注价位
- 简单规则信号
- 模拟仓位计算
- 不连接券商，不自动交易

## 部署到 Streamlit Community Cloud
1. 新建 GitHub 仓库，把本项目全部文件上传到仓库根目录。
2. 打开 Streamlit Community Cloud 并连接 GitHub。
3. Create app → 选择仓库 → 入口文件选择 `streamlit_app.py` → Deploy。
4. 部署完成后，用 iPhone Safari 打开生成的 `streamlit.app` 地址。
5. Safari 分享菜单 → “添加到主屏幕”，即可像 App 一样打开。

## 说明
行情模块使用公开网络接口，可能出现延迟、限流或接口变化。它只适合盯盘原型，不能作为自动交易成交依据。
