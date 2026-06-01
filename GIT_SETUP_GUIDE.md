# Git 远程仓库关联指南

## ✅ 已完成
- [x] 本地 Git 仓库初始化
- [x] 首次提交完成（commit: 65d0710）
- [x] .gitignore 配置（已排除敏感文件）

## 📋 下一步：创建远程仓库并关联

### 方案一：GitHub

#### 1. 创建远程仓库
1. 访问：https://github.com/new
2. 填写信息：
   - **Repository name**: `Defective-Product-Analysis`
   - **Description**: `LVTS 日志自动下载器 - 基于 Playwright 的自动化日志下载工具`
   - **选择**: Private（推荐）或 Public
   - ⚠️ **不要勾选** "Initialize this repository with a README"
3. 点击 "Create repository"

#### 2. 关联远程仓库并推送
创建成功后，在终端执行以下命令：

```powershell
# 添加远程仓库（将 YOUR_USERNAME 替换为您的 GitHub 用户名）
git remote add origin https://github.com/YOUR_USERNAME/Defective-Product-Analysis.git

# 推送到远程仓库
git push -u origin master
```

#### 3. 验证推送
```powershell
git remote -v
git log --oneline
```

---

### 方案二：Gitee（码云）

#### 1. 创建远程仓库
1. 访问：https://gitee.com/projects/new
2. 填写信息：
   - **仓库名称**: `Defective-Product-Analysis`
   - **仓库介绍**: `LVTS 日志自动下载器`
   - **选择**: 私有（推荐）或公开
   - ⚠️ **不要勾选** "使用 Readme 文件初始化这个仓库"
3. 点击 "创建"

#### 2. 关联远程仓库并推送
创建成功后，在终端执行以下命令：

```powershell
# 添加远程仓库（将 YOUR_USERNAME 替换为您的 Gitee 用户名）
git remote add origin https://gitee.com/YOUR_USERNAME/Defective-Product-Analysis.git

# 推送到远程仓库
git push -u origin master
```

---

## 🔐 首次推送认证

### 方式一：使用 Personal Access Token（推荐）
1. **GitHub**: 
   - 访问：https://github.com/settings/tokens
   - 生成新 token（勾选 `repo` 权限）
   - 推送时使用 token 代替密码

2. **Gitee**:
   - 访问：https://gitee.com/profile/personal_access_tokens
   - 生成新 token
   - 推送时使用 token 代替密码

### 方式二：配置 Git 凭据管理器
```powershell
# 启用凭据缓存（15分钟）
git config --global credential.helper cache

# 或使用 Windows 凭据管理器（永久保存）
git config --global credential.helper manager-core
```

---

## 📝 提交的信息

本次提交包含以下文件：
- ✅ `.gitignore` - Git 忽略规则
- ✅ `.qoder/rules/` - Qoder AI 助手规则文件
- ✅ `Log-Download/log_downloader.py` - 主程序
- ✅ `Log-Download/requirements.txt` - Python 依赖
- ✅ `Log-Download/README.md` - 项目说明
- ✅ `Log-Download/run_download_task.bat` - Windows 批处理脚本

**已排除的文件**（不会上传）：
- ❌ `config.json` - 包含服务器密码
- ❌ `downloads/` - 下载的日志文件
- ❌ `*.log` - 运行日志
- ❌ `*.png` - 调试截图
- ❌ `.venv/` - Python 虚拟环境
- ❌ `__pycache__/` - Python 缓存

---

## 🎯 常用 Git 命令

```powershell
# 查看状态
git status

# 查看提交历史
git log --oneline

# 添加修改的文件
git add .

# 提交修改
git commit -m "描述您的修改"

# 推送到远程
git push

# 拉取远程更新
git pull
```

---

## ⚠️ 安全提醒

1. **永远不要提交 `config.json`** - 包含服务器密码
2. 使用环境变量存储敏感信息（已在代码中支持）
3. 定期检查 `.gitignore` 确保敏感文件被正确排除

---

## 📞 需要帮助？

如果在推送过程中遇到问题，可以：
1. 检查网络连接
2. 验证仓库 URL 是否正确
3. 确认用户名和凭据是否正确
4. 查看错误信息并搜索解决方案
