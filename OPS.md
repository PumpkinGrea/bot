# 运维速查（holobot）

服务器部署完成后的日常操作命令。服务名 `holobot`，项目目录假设为 `/home/admin/bot`。

## 查看状态与日志

```bash
# 看服务是否在运行（找 Active: 那一行，绿色 active (running) 即正常）
sudo systemctl status holobot

# 实时看日志（机器人收发消息、报错都在这，Ctrl+C 退出查看，不会停服务）
journalctl -u holobot -f

# 看最近 100 行日志（不实时，适合排查刚才的报错）
journalctl -u holobot -n 100 --no-pager

# 看今天的日志
journalctl -u holobot --since today
```

## 启停与重启

```bash
# 重启（改了代码或配置后，让改动生效）
sudo systemctl restart holobot

# 停止（临时关掉机器人）
sudo systemctl stop holobot

# 启动（停止后重新拉起）
sudo systemctl start holobot

# 开机自启：开启 / 关闭
sudo systemctl enable holobot
sudo systemctl disable holobot
```

## 更新代码（从 GitHub 拉最新）

```bash
cd /home/admin/bot
git pull                              # 拉最新代码
sudo systemctl restart holobot        # 重启生效
sudo systemctl status holobot         # 确认起来了
```

一键版：

```bash
cd /home/admin/bot && git pull && sudo systemctl restart holobot
```

> 注意：`config.yaml` 和 `config_secret.py` 不在仓库里，`git pull` 不会覆盖你服务器上填好的密钥，放心拉。

## 改了 systemd 服务文件后

只要动了 `holobot.service`（本地改完推上来、服务器拉下来），必须重新安装并重载：

```bash
cd /home/admin/bot
sudo cp holobot.service /etc/systemd/system/holobot.service
sudo systemctl daemon-reload          # 重新读取服务配置
sudo systemctl restart holobot
```

## 改了配置 / 密钥后

直接编辑服务器上的文件（这两个文件不入库，改了不影响 git）：

```bash
nano config.yaml            # 改 appid/secret、图片服务端口等
nano config_secret.py       # 改 API key
sudo systemctl restart holobot   # 重启生效
```

## 端口相关（镜像/幻影坦克发不出图时查）

```bash
# 确认图片服务端口在监听
sudo ss -tlnp | grep 9900

# 本机防火墙放行 9900
sudo ufw allow 9900

# 别忘了云厂商控制台的「安全组」也要放行 TCP 9900（网页后台操作）
```

## 排查思路（服务起不来 / 功能不对）

1. `sudo systemctl status holobot` 看是 running 还是 failed
2. failed 就 `journalctl -u holobot -n 50 --no-pager` 看报错，常见原因：
   - 路径填错：`holobot.service` 里的 `WorkingDirectory` / `ExecStart` 和实际对不上
   - python 路径不对：`ExecStart` 要用 `which python3` 查到的绝对路径
   - 配置缺失：`config.yaml` 或 `config_secret.py` 没建或 key 没填
3. 能上线但图片功能报错：多半是 9900 端口没在安全组放行

---

# Clash 代理（clash）

服务器跨境访问 Steam / GitHub 不稳，用 Mihomo(Clash) 做智能分流：
**默认全部直连，只有 Steam/GitHub 等境外域名走代理**。目录假设 `/home/admin/clash`，端口 `7890`。

> 配置文件 `~/clash/config.yaml` 含机场订阅链接（等于代理凭证），不要外传、不要入库。

## 状态与日志

```bash
sudo systemctl status clash            # 看是否 active (running)
journalctl -u clash -f                 # 实时日志
journalctl -u clash -n 30 --no-pager   # 最近30行（排查启动失败）
```

## 启停重启

```bash
sudo systemctl restart clash    # 改了 config.yaml 后生效
sudo systemctl stop clash
sudo systemctl start clash
```

## 验证代理是否通

```bash
# 走代理拉 Steam，出 JSON({"620":...) 即正常
curl -x http://127.0.0.1:7890 -s -m 20 "https://store.steampowered.com/api/appdetails?appids=620&cc=cn&l=zh" | head -c 120; echo
```

## 加一个需要走代理的新网址

编辑 `~/clash/config.yaml` 的 `rules` 段，在 `MATCH,DIRECT` **上面**加一行，改完重启 clash：

```yaml
rules:
  - DOMAIN-SUFFIX,steampowered.com,PROXY
  - DOMAIN-SUFFIX,新域名.com,PROXY       # ← 新增放这，务必在 MATCH 之前
  - MATCH,DIRECT                          # 兜底：其余全直连
```

- `DOMAIN-SUFFIX,xxx.com,PROXY`：该域名及所有子域名都走代理。
- 顺序从上往下匹配、命中即止；放到 `MATCH,DIRECT` 下面会永远不生效。
- `sudo systemctl restart clash` 后生效。

## 切换 / 自动选节点

在 `proxy-groups` 里控制：

```yaml
proxy-groups:
  - name: PROXY
    type: url-test          # 自动测速选最快；手动选则用 select
    use:
      - airport
    url: https://www.gstatic.com/generate_204
    interval: 300           # 每5分钟重测，自动切到延迟最低的节点
    tolerance: 50
```

改完 `sudo systemctl restart clash`。订阅节点每天自动更新一次（`proxy-providers` 里 `interval: 86400`）。

## 谁在走代理

- **bot**：`holobot.service` 里配了 `HTTPS_PROXY=http://127.0.0.1:7890`，但 Clash 按规则分流——
  智谱/QQ 等国内域名仍直连，只有 Steam 等命中 PROXY 规则的才真正过代理。改代理规则不用动 bot。
- **git**：`git config --global http.proxy http://127.0.0.1:7890`（GitHub 拉取走代理）。
  想临时关掉：`git config --global --unset http.proxy`。

## 排查（查游戏又连不上时）

1. `sudo systemctl status clash` 确认代理在跑
2. 跑上面「验证代理是否通」那条 curl，看代理本身能否连 Steam
3. 通但 bot 查不到 → 确认 `holobot.service` 的 proxy 环境变量还在（`systemctl show holobot -p Environment`）
4. 代理都连不上 → 多半机场节点挂了，看 `journalctl -u clash -n 30`，或订阅是否过期
