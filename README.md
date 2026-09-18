# jev

[![CI](https://github.com/okooo5km/jev/actions/workflows/ci.yml/badge.svg)](https://github.com/okooo5km/jev/actions/workflows/ci.yml)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](jev/scripts/jev)

**命令行里的类型化判断：`yes`/`pick`/`score`，每个答案都带校准概率 —— TypeSafe Jev 通过 OpenRouter 调用，CLI + Agent Skill。**

中文 · [English](README.en.md)

`jev` 是非官方的社区封装，只支持 OpenRouter 这一个后端；不隶属于 TypeSafe 或 OpenRouter。单文件、仅
标准库、Python 3.9+，一次调用约 1 秒、约 $0.00002。

作者：**okooo5km(十里)**。更多技能：[sink.5km.tech/skills](https://sink.5km.tech/skills)。

```bash
$ jev yes "用户在要求退款吗？" -s "Zipic 一打开就闪退，钱退我！"
yes	0.97

$ jev pick "该交给谁处理" code="写代码或改项目" research="需要联网查资料" --other -s "帮我写一个 Python 脚本"
code

$ jev score "这条评价给几星" --range 1-5 -s "还不错，但有点小问题"
3.73	4

$ jev run mail -s "主题：您的 App 审核已通过 ..."
category     app_review  p=1.00 conf=1.00
urgency      今天处理    score=1.41/3 conf=0.15
needs_reply  no          p=0.05
is_promo     no          p=0.09
```

## 1. 安装 CLI（macOS / Linux）

```sh
curl --proto '=https' --tlsv1.2 -fLsS https://github.com/okooo5km/jev/releases/download/v0.1.0/install.sh -o /tmp/jev-install.sh
sh /tmp/jev-install.sh
export PATH="$HOME/.local/bin:$PATH"
jev --version
```

先下载到本地再执行，方便自己看一眼脚本内容。要求：`python3` ≥ 3.9、`curl`、`tar`、`shasum` 或
`sha256sum`。写入位置：技能文件夹（CLI + 内置 specs + 文档）到
`${XDG_DATA_HOME:-~/.local/share}/jev/`，再把 `~/.local/bin/jev` 软链到其中的 `scripts/jev`。不
碰 shell 配置文件，不需要 sudo，重复运行是安全的（幂等）。

环境变量覆盖：`JEV_VERSION`（默认 `v0.1.0`）、`JEV_HOME`（技能文件夹位置）、`JEV_INSTALL_DIR`
（软链位置，默认 `~/.local/bin`）、`JEV_ARCHIVE_DIR`（离线安装，指向已下载好压缩包+校验文件的目录）。

手动安装：从 [Releases](https://github.com/okooo5km/jev/releases/latest) 下载
`jev-vX.Y.Z.tar.gz`、对应的 `.sha256` 和 `install.sh`，放在同一目录，校验后离线安装：

```sh
shasum -a 256 -c jev-v0.1.0.tar.gz.sha256
JEV_ARCHIVE_DIR=. sh install.sh
```

Windows：未测试，请用 WSL。

卸载：

```sh
rm -f ~/.local/bin/jev
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/jev"
rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/jev"   # 可选：一并删除密钥和自定义 spec
```

## 2. 安装技能

```sh
npx skills add okooo5km/jev -g
```

只有这条安装命令需要 Node.js，CLI 本身不需要。可选 `-a claude-code codex ...` 指定安装到哪些
Agent。技能内置了 CLI（`scripts/jev`），首次使用时 Agent 按技能说明把它链接到 `~/.local/bin`。更新
`npx skills update jev -g`，卸载 `npx skills remove jev -g`。

```text
用 jev 判断这条工单是不是要求退款。
把这批评论跑一遍 jev run feedback，标出需要人工处理的。
```

## 3. 配置 OpenRouter 密钥

在 [openrouter.ai/keys](https://openrouter.ai/keys) 创建一个密钥。二选一：

```sh
# A. 环境变量（写进 shell 配置文件、密钥管理器，或 CI secret）
export OPENROUTER_API_KEY=sk-or-...

# B. 配置文件
mkdir -p ~/.config/jev && ${EDITOR:-vi} ~/.config/jev/.env
# 写入一行：OPENROUTER_API_KEY=sk-or-...
chmod 600 ~/.config/jev/.env
```

查找顺序：环境变量 → `$JEV_ENV_FILE` → `~/.config/jev/.env`（`XDG_CONFIG_HOME` 可覆盖配置目录）。
没有 `./.env`（当前目录）这一项——密钥属于用户，不属于某个仓库。永远不要把密钥贴进聊天，也不要当
命令行参数传递。

## 4. 快速上手

| 动词 | 用途 | 输出 | 退出码 |
|---|---|---|---|
| `yes` | 是非判断 | `yes\t0.97` | 0 yes · 1 no · 2 出错 |
| `pick` | 多选一 | 选中的选项名 | 0 完成 · 1 低于 `--min-confidence` · 2 出错 |
| `score` | 有序打分 | `VALUE\tLABEL` | 0 完成 · 2 出错 |
| `filter` | 语义 grep | 命中的原始行 | 0 有命中 · 1 无命中 · 2 有行出错 |
| `run` | 一次问多个问题 | 对齐的表格 | 0 完成 · 2 出错 |
| `raw` | 原始请求体 | 响应 JSON | 0 完成 · 2 出错 |

```bash
# 逐行模式：一行一次判断，8 路并发，保持输入顺序
printf '%s\n%s\n' '{"text":"希望支持深色模式"}' '{"text":"闪退三次，要求退款"}' \
  | jev run feedback -l --field text --json

# --json：拿到完整概率分布和 usage，供脚本消费
jev run route -s "帮我看看今天有没有重要邮件" --json

# 接实时日志，只留下值得关注的行
tail -f app.log | jev filter "日志表示用户可见的故障" --false "调试信息、正常请求"
```

## 5. 写好问题

Jev 按字面理解条件，不会脑补言外之意：

- 描述可观察的条件，而不是目标；`--true`/`--false` 或 `criteria` 把两边都说清楚。
- 选项要覆盖穷尽，覆盖不全就加 `--other`。
- 刻度标签从低到高排列，2–10 个。
- 同一份状态要问多个问题，合并进一个 spec 一次问完（成本几乎不变）。
- 状态只放判断需要的内容，不要糊一整篇原文进去。

实测反例：`jev filter "包含具体可行动的信息"` 把「加微信领取免费 AI 课程，限时三天」判成约 0.9 命中
——按字面它确实"可行动"。改成 `jev filter "消息给出了具体的技术、产品或行业信息" --false
"闲聊、问候、广告、引流、卖课"` 后，同一条消息被正确排除（`exit 1`，未命中）。

## 6. 模板

`jev run` 列出可用 spec。内置 5 个，均为 JSON（任何 3.9+ 都能读）：

| 名称 | 判断内容 |
|---|---|
| `mail` | 邮件分类、紧急度、是否需要回复、是否纯广告 |
| `feedback` | 反馈意图、情绪、是否需要人工、流失风险 |
| `signal` | 群消息/推文是否值得看、话题、新颖度 |
| `commit` | Conventional Commit 类型、密钥泄露、破坏性变更、风险 |
| `route` | 请求该交给哪种处理方式、复杂度、是否需要联网/私有数据 |

自定义 spec 放在 `~/.config/jev/specs/`（`XDG_CONFIG_HOME` 可覆盖），JSON 或 TOML 均可——JSON 在
任何 3.9+ 都能用，TOML 需要 3.11+（`tomllib`），版本不够会给出明确报错而不是崩溃：

```json
{
  "description": "一句话说明这个 spec 是干什么的",
  "threshold": 0.5,
  "questions": {
    "urgent": { "type": "noul", "instructions": "是否紧急",
                "criteria": { "true": "需要立刻处理", "false": "可以排期" } }
  }
}
```

```toml
description = "一句话说明这个 spec 是干什么的"
threshold = 0.5

[questions.urgent]
type = "noul"
instructions = "是否紧急"
[questions.urgent.criteria]
true = "需要立刻处理"
false = "可以排期"
```

每个问题只认 `type`、`instructions`、`criteria` 三个字段，写了别的字段会直接报错，不会被悄悄丢掉。是非题
两端的描述放进 `criteria`，`true` 和 `false` 都要写。

## 7. 费用与限制

输入 $0.042/M token，输出免费；单次调用约 1 秒，约 $0.00002（1000 次约 $0.02）。状态+最长问题建议
控制在 32K token 以内。`score` 最多 10 个等级（API 硬限制）。速率限制约 1,200 请求/分钟，`-j`/逐行
并发建议不超过 16。接口是 OpenRouter 的 alpha 端点，如有变化用 `JEV_BASE_URL` 覆盖。Jev 只做决策，
不生成文本——过滤之后的内容仍需要你自己读、写或总结。

## 8. 开发与验证

```sh
python3 -m unittest discover -s tests -v      # 离线，纯标准库，不需要真实密钥
shellcheck -s sh installers/install.sh .github/package.sh
sh .github/package.sh v0.1.0                  # 产出 dist/jev-v0.1.0.tar.gz(.sha256)
gh release create v0.1.0 dist/* installers/install.sh
```

## 许可

Apache-2.0，见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。独立社区项目，与 TypeSafe、OpenRouter 无
官方隶属关系。欢迎查看十里的[更多技能](https://sink.5km.tech/skills)，也欢迎 Star 或提交 PR。
