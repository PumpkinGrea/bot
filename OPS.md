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

## SVWB 卡组数据同步

`查卡组` 和 `卡组梯度` 只读取 `data/svwb/snapshot.json`，不会在 QQ 查询时访问 SVWB 或第三方转发服务。`svwb_sync.py` 使用 Playwright 启动 Chromium，打开 SVWB、执行网页 JavaScript，并把五份公开数据原子写入本地快照；失败时保留上一份快照。

首次部署或更新后执行：

```bash
cd /home/admin/bot
sudo python3 -m pip install --break-system-packages playwright
sudo python3 -m playwright install --with-deps chromium
# Playwright 浏览器文件要安装到运行同步服务的 admin 用户目录
sudo -u admin -H env HOME=/home/admin /usr/bin/python3 -m playwright install chromium
sudo -u admin -H env HOME=/home/admin /usr/bin/python3 svwb_sync.py
sudo cp svwb-sync.service svwb-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now svwb-sync.timer
sudo systemctl restart holobot
```

检查同步状态：

```bash
systemctl list-timers svwb-sync.timer
sudo journalctl -u svwb-sync.service -n 50 --no-pager
ls -lh /home/admin/bot/data/svwb/snapshot.json
```

默认直连 SVWB。只有在 `config.yaml` 中明确填写 `svwb_proxy` 时，同步浏览器才使用该代理；不会复用 Steam 代理。旧的 Jina 转发和机器人在线抓取路径已经移除。

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

服务器跨境访问 Steam / GitHub 不稳，用 Mihomo(Clash) 在本机提供一个代理服务
（监听 `127.0.0.1:7890`）。Clash 内部按规则分流：命中 PROXY 的域名走境外节点、
其余直连。目录假设 `/home/admin/clash`。

> 配置文件 `~/clash/config.yaml` 含机场订阅链接（等于代理凭证），不要外传、不要入库。

## ⚠️ 核心概念：clash 只是"提供"代理，谁用它得逐个显式指定

Linux 没有"全局代理总开关"。装了 clash、Steam 能通，**不代表所有程序都自动走代理**。
每个程序怎么用代理是各管各的，必须一个个显式告诉它：

| 程序 | 怎么让它走代理 |
|---|---|
| bot（查游戏/查玩家） | 代码从 `config.yaml` 读 `steam_proxy`，只挂到 Steam 请求上 |
| bot（Pixiv 搜图） | 代码从 `config.yaml` 读 `pixiv_proxy`，只挂到 Pixiv 搜图接口和图片 CDN 上 |
| git（拉代码） | `git config --global http.proxy http://127.0.0.1:7890` |
| curl（手动测试） | 加 `-x http://127.0.0.1:7890` 参数 |

它们互不相干：给 bot 配了代理，git 不会跟着走；curl 能通，也不代表 git 能通。
**曾经的坑**：以为 `systemctl edit holobot` 加 `HTTPS_PROXY` 就行——但那变量没进到进程里
（`systemctl show holobot -p Environment` 是空的），所以改成了代码里显式读 `steam_proxy`。
别再依赖 systemd 环境变量那套。

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

## 手动更新订阅与查看节点延迟

以下命令在服务器终端执行。当前订阅名称为 `airport`，代理组为 `PROXY`，控制接口只监听 `127.0.0.1:9090`；不要将控制端口开放到公网。更新和测速不需要重启 Clash。显示结果使用 `jq`，未安装时执行 `sudo apt install -y jq`。

### 1. 更新订阅

```bash
curl -sS --max-time 60 -X PUT \
  http://127.0.0.1:9090/providers/proxies/airport \
  -w '\nHTTP %{http_code}\n'
```

返回 `HTTP 204` 表示更新成功，不代表节点已经可用。查看更新时间与节点数量：

```bash
curl -fsS --max-time 10 http://127.0.0.1:9090/providers/proxies/airport |
jq '{更新时间: .updatedAt, 节点数量: (.proxies | length)}'
```

### 2. 重新测试所有订阅节点

```bash
curl -sS --max-time 60 \
  http://127.0.0.1:9090/providers/proxies/airport/healthcheck \
  -w '\nHTTP %{http_code}\n'
```

测速可能需要几十秒。`HTTP 204` 表示本次检查已完成，不代表所有节点通过；结果用下一条命令查看。如果请求超时，可稍后查看最新结果。

### 3. 查看节点延迟

```bash
curl -fsS --max-time 10 http://127.0.0.1:9090/providers/proxies/airport |
jq -r '.proxies[] |
  [.name, (if (.history | length) == 0 then "尚无测速记录"
    elif .alive and (.history[-1].delay > 0)
    then ((.history[-1].delay | tostring) + " ms")
    else "不可用/超时"
  end)] | @tsv'
```

延迟是通过节点请求健康检查网址的耗时，不是 ping 延迟。当前订阅使用 `https://www.gstatic.com/generate_204`；测试失败时记录中的 `delay: 0` 不代表零延迟。测速记录不是实时保证，访问 GitHub 是否成功还应单独验证。

### 4. 查看当前选中节点

```bash
curl -fsS --max-time 10 http://127.0.0.1:9090/proxies/PROXY |
jq '{当前节点: .now, 类型: .type}'
```

当前模式为 `rule`，GitHub 等命中规则的请求使用 `PROXY`。此时 `GLOBAL` 显示 `DIRECT` 不能单独证明请求没有走代理，应查看实际命中的代理组。

### 5. 验证 GitHub 是否恢复

```bash
curl -I -x http://127.0.0.1:7890 \
  --connect-timeout 10 --max-time 20 https://github.com
```

只有 `200 Connection established` 表示本地代理接受了隧道请求，还需要后续 GitHub 的 HTTP 响应。如果所有节点仍不可用，或选中的是“剩余流量”等说明记录，不能认为代理已经恢复。可对比 Windows 上同一订阅的可用节点，并检查节点域名解析和连接情况；更新订阅成功与线路可用是两回事。

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

## 让 bot 走代理

编辑 `config.yaml`，填 `steam_proxy`，重启即可（只有 Steam 请求走代理，智谱/QQ 不受影响）：

```bash
nano /home/admin/bot/config.yaml
#   steam_proxy: "http://127.0.0.1:7890"
sudo systemctl restart holobot
journalctl -u holobot -n 30 | grep Steam    # 应出现 "已启用 Steam 专用代理"
```

Pixiv 搜图默认自动复用 `steam_proxy`，所以已有 Steam 代理时无需另配。若要给 Pixiv 指定不同线路，再在 `config.yaml` 填：

```yaml
pixiv_proxy: "http://127.0.0.1:7890"
```

重启机器人后，`journalctl -u holobot -n 30 | grep Pixiv` 应出现“已启用 Pixiv 专用代理”。

## 让 git 走代理（git pull 卡住时必配）

git 是独立程序，不会因为 bot 配了代理就跟着走，必须单独配：

```bash
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
git config --global --get http.proxy         # 确认配上了
# 想临时关掉（比如直连更快时）：
git config --global --unset http.proxy
git config --global --unset https.proxy
```

## 排查：git pull 一直没反应

1. `git config --global --get http.proxy` 看 git 配没配代理
   - 空 → git 在直连 GitHub，跨境不稳会卡。按上面「让 git 走代理」配上。
   - 有值 → 确认端口和 clash 一致（下一步）。
2. `sudo ss -tlnp | grep 7890` 看 clash 监听的端口，要和 git 配的一致。
3. `curl -x http://127.0.0.1:7890 -s -m 20 -o /dev/null -w "%{http_code}\n" https://github.com`
   出 200/301 = 代理连 GitHub 正常；卡住 = 节点问题，换节点或看 clash 日志。
4. 还卡就看 git 卡在哪一步：`GIT_CURL_VERBOSE=1 git pull 2>&1 | head -40`
   - 卡在 `Trying 127.0.0.1:7890` → 代理没起/端口错
   - 卡在 `Receiving objects` → 连上了在拉数据，是慢不是断，等或换节点

## 排查：查游戏又连不上

1. `sudo systemctl status clash` 确认代理在跑
2. 跑上面「验证代理是否通」那条 curl，看代理本身能否连 Steam
3. 通但 bot 查不到 → 确认 `config.yaml` 的 `steam_proxy` 填了、且 `journalctl -u holobot | grep Steam` 有"已启用代理"
4. 代理都连不上 → 多半机场节点挂了，看 `journalctl -u clash -n 30`，或订阅是否过期
