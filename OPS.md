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
