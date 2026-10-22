"""B12 JWT token_version 认证校验

背景：改密 / 强制下线后，此前签发的 access token 在有效期内（默认 12 小时）依然可用——
SimpleJWT 的黑名单只校验 refresh token，挡不住 access。

方案：User.token_version 单调递增；
- 签发（登录 / 注册 / 刷新派生）时把当前版本写进 token 的 tv claim；
- 认证时比对 claim 与用户当前版本，不一致即视为失效（401），前端按 401 流程刷新 / 跳登录。

tv 缺失（升级前签发的历史 token）一律视为失效——宁可全员重新登录一次，
也不给「改密后旧 token 仍有效」留后门。
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class TokenVersionJWTAuthentication(JWTAuthentication):
    """在标准 JWT 认证之上追加 token_version（tv claim）校验"""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user is None:
            return None
        tv = validated_token.get("tv")
        if tv is None or tv != user.token_version:
            # 版本对不上：token 签发后发生过改密 / 强制下线 / 管理员重置密码
            raise InvalidToken("登录态已失效，请重新登录")
        return user
