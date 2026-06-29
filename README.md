# Holo QQ 机器人

基于 QQ 官方开放平台（[botpy](https://github.com/tencent-connect/botpy)）的群聊 / 私聊机器人，人设为「贤狼赫萝」。

## 功能

群里 @ 机器人（私聊直接发）即可触发：

- **聊天**：`@咱 + 文字` 智谱 GLM 对话，带上下文记忆；`@咱 + 图片` 识图；`@咱 清空对话` 重置记忆
- **今日运势**：`@咱 今日运势`，同人同天结果固定
- **随机二次元图**：`@咱 来张图` / `二次元`
- **AI 生图**：`@咱 画图 描述`（如「画图 戴帽子的猫」）
- **镜像**：`@咱 镜像` + 一张图，左右对称（支持 GIF）
- **幻影坦克**：`@咱 幻影坦克` + 两张图
- **小工具**：随机数 / 掷骰子 / 抛硬币 / 选择 / 复读 / 在吗 / 菜单

## 配置

- `config.yaml`：appid、secret、图片服务设置（**含密钥，不入库**）
- `config_secret.py`：智谱 GLM、生图中转站的 API key（**含密钥，不入库**）

两者都已在 `.gitignore` 里，部署时需单独上传。

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -r requirements.txt
python bot.py
```

镜像/幻影坦克要让公网能拉到本机生成的图。本地开发用内网穿透（如 cpolar）：

```bash
cpolar http 9900
# 把得到的 https://xxxx.cpolar.cn 填进 config.yaml 的 img_public_base（末尾无斜杠）
```

> 不配 `img_public_base` 且非服务器环境时，镜像/幻影坦克自动关闭，其它功能照常。

## 部署到 Linux 服务器（有公网 IP，推荐）

服务器本身在公网，**无需内网穿透**。

1. 装环境并安装依赖
   ```bash
   sudo apt update && sudo apt install -y python3 python3-venv python3-pip
   cd ~/holo
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. 上传 `config.yaml` 和 `config_secret.py`（被 gitignore，不会随仓库带过来）。
   `config.yaml` 里 `img_public_base` **留空即可**——程序会自动探测服务器公网 IP，
   拼成 `http://<公网IP>:9900`。若有域名 + Nginx，可手动填 `https://你的域名`。

3. **放行端口**：云厂商安全组放行 `9900`；服务器防火墙 `sudo ufw allow 9900`。
   （镜像/幻影坦克需要 QQ 服务器能访问这个端口来拉图。）

4. 常驻运行（用自带的 systemd 模板）
   ```bash
   # 编辑 holobot.service，把 <USER> 和路径换成你的真实值
   sudo cp holobot.service /etc/systemd/system/holobot.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now holobot
   sudo systemctl status holobot       # 查看状态
   journalctl -u holobot -f            # 实时日志
   ```
   改代码后：`sudo systemctl restart holobot`

## 架构

```
QQ 开放平台 ── WebSocket ──> bot.py (botpy 事件循环)
                                │
                ┌───────────────┼────────────────┬──────────────┐
            handle_text     ai_module          图片功能       image_host
            （运势/工具/    （GLM 对话/识图）  acg/gpt_draw    （本机起 HTTP
              菜单）                            pic_handle       托管处理后的图，
                                              （镜像/坦克）     供 QQ 拉取）
```

- **发图限制**：官方平台发图只收**公网 jpg/png URL**，不收 base64/本地文件。
  随机图、生图返回的本就是公网 URL；镜像/幻影坦克是本地生成，须经 `image_host` 暴露。
- **防阻塞**：botpy 是单线程异步循环，所有同步网络/图像调用都用 `asyncio.to_thread` 包装。
- **未迁移**（受官方平台能力限制）：非 @ 的关键词自动回复（收不到未 @ 的群消息）、
  启动群发公告（无群列表 API、不能主动群发）。
```
