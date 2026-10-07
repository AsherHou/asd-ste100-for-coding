# plan-first plugin

This folder is the plan-first plugin for Claude Code. Installing the plugin copies only this folder.

- `skills/plan-first/`: the English skill.
- `skills/plan-first-zh/`: the Chinese skill.
- `rules/en/` and `rules/zh-CN/`: the same rules and the human doc template as plain files, for `CLAUDE.md` or `AGENTS.md`.

Install it in Claude Code:

```
/plugin marketplace add AsherHou/asd-ste100-for-coding
/plugin install plan-first@asd-ste100-for-coding
```

You can also copy `skills/plan-first` (or `skills/plan-first-zh`) into `~/.claude/skills/`.

The [main README](../README.md) explains what it does, how I tested it and the other ways to install it.

---

这是 plan-first 的 Claude Code 插件本体，安装插件时只会拷贝这个文件夹。里面有英文和中文两个 skill，以及内容相同的规则文件。用法和其他安装方式见[主页 README](../README.zh.md)。
