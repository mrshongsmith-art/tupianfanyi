# tupianfanyi

`tupianfanyi` 是一个用于 AstrBot 的图片翻译插件，支持通过有道或百度图片翻译接口处理群聊和私聊中的图片，并返回翻译后的图片。

## 功能特性

- 支持发送图片时直接触发图片翻译。
- 支持先发送翻译命令，再在 60 秒内补发图片。
- 支持识别回复消息中的图片。
- 支持有道图片翻译和百度图片翻译。
- 支持切换优先使用的翻译 API。
- 支持按图片内容和 API 类型缓存翻译结果，减少重复请求。

## 安装方式

将本插件目录复制到 AstrBot 插件目录中：

```text
data/plugins/tupianfanyi
```

安装依赖：

```bash
pip install -r requirements.txt
```

然后重启 AstrBot，或在 AstrBot 控制台中重新加载插件。

## 配置说明

插件配置来自 AstrBot 面板，对应字段定义在 `_conf_schema.json`。

可配置项：

- `baidu_app_id`：百度翻译开放平台 APP ID。
- `baidu_app_key`：百度翻译开放平台密钥。
- `youdao_app_key`：有道智云应用 ID。
- `youdao_app_secret`：有道智云应用密钥。
- `priority_api`：优先使用的翻译 API，可选 `youdao` 或 `baidu`。

至少需要配置一组可用的翻译 API 凭据：

- 有道：`youdao_app_key` 和 `youdao_app_secret`
- 百度：`baidu_app_id` 和 `baidu_app_key`

## 使用方式

发送以下任意命令触发图片翻译：

- `图片翻译`
- `翻译图片`

常见用法：

- 发送 `图片翻译` 并附带图片。
- 回复一条包含图片的消息并发送 `图片翻译`。
- 先发送 `图片翻译`，再根据提示在 60 秒内发送图片。
- 在等待图片时发送 `退出` 可取消本次翻译。

切换翻译 API：

```text
/切换翻译api youdao
/切换翻译api baidu
```

不带参数发送 `/切换翻译api` 可以查看当前优先 API 和可选项。

## 缓存说明

插件会在 `cache/` 目录保存翻译后的图片缓存。缓存目录属于运行产物，不建议上传到仓库。

## 使用注意

- 翻译质量和成功率取决于第三方翻译 API。
- 图片过大时插件会尝试压缩后再请求接口。
- 请妥善保管第三方平台的 App Key、Secret 和密钥，不要提交到公开仓库。

## 开源许可

本项目采用 `LICENSE` 文件中的开源许可。

你可以自由使用、复制、修改、分发和二次开发本项目，但需要保留原始版权声明和许可声明。
