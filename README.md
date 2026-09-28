# Piastri World Circuit 云端补货监控

定时在 GitHub Actions（或任何常驻服务器）上检查 Oscar Piastri 官方商店
World Circuit 三件商品的 XS/S/M 是否补货；检测到补货时通过 Bark 推送 iPhone。
由于运行在云端，Mac 合盖睡眠不影响监控。

## 监控范围

- World Circuit T-Shirt - Off White（XS/S/M）
- World Circuit Quarter Zip - Burgundy（XS/S/M）
- World Circuit Layered T-Shirt - Blue（XS/S/M）

## 部署（GitHub Actions）

1. 创建私有仓库并推送本目录内容（monitor.py、world-circuit-stock.json、
   .github/workflows/piastri-restock.yml）。
2. 在仓库 Settings → Secrets and variables → Actions 添加：
   - `BARK_ENDPOINT` = `https://api.day.app`
   - `BARK_DEVICE_KEY` = Bark 设备 key
3. Workflow 已配置每 5 分钟运行一次，也可在 Actions 页手动触发。

基线文件在相关库存状态变化时才会被更新并提交，不会在每次无变化运行时刷屏。
推送失败时不会推进基线，下一次运行会自动重试。
