# RELEASE CHECKLIST

## 功能验证
- [ ] xstrm 菜单可启动
- [ ] xstrm-admin 菜单可启动
- [ ] 扫描指定目录可生成 `.strm`
- [ ] 已发现目录选择扫描可用
- [ ] 去重逻辑正确
- [ ] 简单样本播放成功
- [ ] 复杂样本播放成功

## 配置链路
- [ ] `runtime.yaml` 可填写
- [ ] `render_runtime.py` 可运行
- [ ] `apply_runtime.py` 可运行
- [ ] `constant.js` 已被 runtime 覆盖
- [ ] `constant-mount.js` 已被 runtime 覆盖
- [ ] `sites-enabled` 配置已生成

## 部署防呆
- [ ] python3 检查通过
- [ ] PyYAML 检查通过
- [ ] nginx 安装检查通过
- [ ] https 模式下证书路径校验通过
- [ ] nginx -t 校验通过
- [ ] reload 流程可用

## 发布收口
- [ ] README 完整
- [ ] BOOTSTRAP_USAGE 完整
- [ ] RUNTIME_CONFIG_DESIGN 完整
- [ ] CHANGELOG 初版
- [ ] LICENSE 确认
- [ ] 仓库无运行时脏文件
