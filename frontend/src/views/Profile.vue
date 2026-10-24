<template>
  <!-- ================= F617 个人公开主页（/u/:username，可免登录访问） ================= -->
  <div v-if="publicMode" class="min-h-screen bg-ink-50 p-4 sm:p-8">
    <div class="mx-auto max-w-2xl space-y-4">
      <div v-if="pubLoading" class="card p-8 text-center text-[13px] text-ink-400">加载中…</div>
      <div v-else-if="pubError" class="card p-8 text-center">
        <div class="text-[28px]">🫥</div>
        <div class="mt-2 text-[13px] text-ink-500">{{ pubError }}</div>
        <button class="btn-outline mt-4 text-[12px]" @click="goHome">返回首页</button>
      </div>
      <template v-else-if="pub">
        <div class="card overflow-hidden">
          <div class="h-20 bg-gradient-to-r from-brand-500 to-indigo-500"></div>
          <div class="px-6 pb-6">
            <div class="-mt-8 flex items-end gap-4">
              <img v-if="pub.avatar" :src="pub.avatar" class="h-16 w-16 rounded-full border-4 border-white object-cover bg-white" />
              <div v-else class="grid h-16 w-16 place-items-center rounded-full border-4 border-white bg-brand-100 text-[22px] font-bold text-brand-700">{{ (pub.display_name || pub.username).slice(0, 1) }}</div>
              <div class="flex-1 pb-1">
                <div class="flex items-center gap-2">
                  <span class="text-[16px] font-semibold text-ink-900">{{ pub.display_name }}</span>
                  <span v-if="pub.is_online" class="tag bg-emerald-50 text-emerald-600">在线</span>
                  <span v-for="r in pub.role_names || []" :key="r" class="tag tag-brand">{{ r }}</span>
                </div>
                <div class="text-[12px] text-ink-400">@{{ pub.username }}<span v-if="pub.department"> · {{ pub.department }}</span></div>
              </div>
              <button v-if="!pub.is_self" class="btn-primary shrink-0 text-[12px]"
                      :disabled="followBusy" @click="toggleFollowPub">
                {{ pub.is_following ? '已关注' : '＋ 关注' }}
              </button>
            </div>
            <p class="mt-3 text-[13px] leading-relaxed text-ink-600">{{ pub.bio || '这个人很低调，还没有填写简介。' }}</p>
            <div class="mt-3 flex flex-wrap gap-1.5">
              <span v-for="t in pub.tags || []" :key="t" class="tag">{{ t }}</span>
            </div>
            <div class="mt-4 grid grid-cols-4 gap-2 text-center">
              <div class="rounded-control bg-ink-50 py-2">
                <div class="text-[16px] font-bold text-ink-900">{{ pub.stats?.followers ?? 0 }}</div>
                <div class="text-[11px] text-ink-400">粉丝</div>
              </div>
              <div class="rounded-control bg-ink-50 py-2">
                <div class="text-[16px] font-bold text-ink-900">{{ pub.stats?.following ?? 0 }}</div>
                <div class="text-[11px] text-ink-400">关注</div>
              </div>
              <div class="rounded-control bg-ink-50 py-2">
                <div class="text-[16px] font-bold text-ink-900">{{ pub.stats?.notes ?? 0 }}</div>
                <div class="text-[11px] text-ink-400">笔记</div>
              </div>
              <div class="rounded-control bg-ink-50 py-2">
                <div class="text-[16px] font-bold text-ink-900">{{ pub.stats?.files ?? 0 }}</div>
                <div class="text-[11px] text-ink-400">文件</div>
              </div>
            </div>
            <div class="mt-4 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
              <span>加入于 {{ (pub.date_joined || '').slice(0, 10) }}</span>
              <span v-if="pub.last_active_at">· 最近活跃 {{ formatTime(pub.last_active_at) }}</span>
              <button class="btn-ghost ml-auto text-[12px]" @click="copyProfileLink">复制主页链接</button>
            </div>
          </div>
        </div>
        <div v-if="(pub.badges || []).length" class="card p-5">
          <h2 class="text-[15px] font-semibold text-ink-800">徽章</h2>
          <div class="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-6">
            <div v-for="b in pub.badges" :key="b.name" class="flex flex-col items-center gap-1 rounded-control bg-amber-50 p-2 text-center">
              <span class="text-[20px]">{{ b.icon }}</span>
              <span class="text-[11px] font-medium">{{ b.name }}</span>
            </div>
          </div>
        </div>
        <div class="text-center text-[11px] text-ink-400">
          这是 {{ pub.display_name }} 的公开主页 ·
          <button class="text-brand-600 hover:underline" @click="goHome">返回平台</button>
        </div>
      </template>
    </div>
  </div>

  <!-- ================= 个人设置（/profile） ================= -->
  <div v-else class="mx-auto max-w-2xl space-y-4">
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">个人资料</h2>
      <div class="mt-4 flex items-center gap-4">
        <div class="relative">
          <img v-if="avatarPreview" :src="avatarPreview" class="h-16 w-16 rounded-full object-cover" />
          <img v-else-if="user.profile?.avatar" :src="user.profile.avatar" class="h-16 w-16 rounded-full object-cover" />
          <div v-else class="grid h-16 w-16 place-items-center rounded-full bg-brand-100 text-[20px] font-bold text-brand-700">{{ user.displayName.slice(0, 1) }}</div>
        </div>
        <div class="space-y-1.5">
          <button class="btn-outline text-[12px]" @click="avatarInput?.click()">更换头像</button>
          <input ref="avatarInput" type="file" accept="image/*" class="hidden" @change="onAvatarSelect" />
          <button v-if="user.profile?.avatar" class="block btn-ghost px-2 text-[12px] text-rose-500" @click="removeAvatar">移除头像</button>
        </div>
      </div>
      <!-- 头像裁剪预览 -->
      <div v-if="cropModal" class="mt-4 rounded-control border border-ink-100 p-3">
        <div class="text-[12px] text-ink-600">调整头像（拖拽选择区域）</div>
        <div class="mt-2 flex justify-center">
          <canvas ref="cropCanvas" width="200" height="200" class="rounded-full"></canvas>
        </div>
        <div class="mt-2 flex justify-end gap-2">
          <button class="btn-ghost text-[12px]" @click="cropModal = false">取消</button>
          <button class="btn-primary text-[12px]" @click="doCropAndUpload">确认裁剪</button>
        </div>
      </div>
      <div class="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-[12px] font-medium text-ink-600">用户名（登录名）</label>
          <div class="flex gap-2">
            <input v-model="username" class="input" />
            <button class="btn-outline shrink-0 text-[12px]" @click="saveUsername">修改</button>
          </div>
        </div>
        <div><label class="mb-1 block text-[12px] font-medium text-ink-600">昵称</label><input v-model="form.nickname" class="input" /></div>
        <div><label class="mb-1 block text-[12px] font-medium text-ink-600">邮箱</label><input v-model="form.email" class="input" /></div>
        <div><label class="mb-1 block text-[12px] font-medium text-ink-600">手机号</label><input v-model="form.phone" class="input" /></div>
        <div class="sm:col-span-2"><label class="mb-1 block text-[12px] font-medium text-ink-600">个人简介</label><textarea v-model="form.bio" class="input h-20 resize-none"></textarea></div>
        <div class="sm:col-span-2">
          <label class="mb-1 block text-[12px] font-medium text-ink-600">个人标签（逗号分隔）</label>
          <input v-model="tagsInput" class="input" placeholder="如：设计,前端,摄影" />
        </div>
      </div>
      <div class="mt-4 flex justify-end"><button class="btn-primary" @click="saveProfile">保存资料</button></div>
    </div>

    <!-- #49 我的徽章 -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">我的徽章</h2>
      <div class="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-8">
        <div v-for="b in badges" :key="b.key" class="flex flex-col items-center gap-1 rounded-control p-2 text-center"
             :class="b.earned ? 'bg-amber-50' : 'opacity-40'">
          <span class="text-[24px]">{{ b.icon }}</span>
          <span class="text-[11px] font-medium">{{ b.name }}</span>
          <span class="text-[10px] text-ink-400">{{ b.earned ? '已获得' : b.rule }}</span>
        </div>
      </div>
    </div>

    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">修改密码</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <input v-model="pwd.old_password" type="password" class="input" placeholder="原密码" />
        <input v-model="pwd.new_password" type="password" class="input" placeholder="新密码（至少 6 位）" @input="checkPwdStrength" />
        <input v-model="pwd.confirm" type="password" class="input" placeholder="确认新密码" />
      </div>
      <!-- #50 密码强度条 -->
      <div v-if="pwd.new_password" class="mt-2">
        <div class="flex gap-1">
          <div v-for="i in 5" :key="i" class="h-1.5 flex-1 rounded"
               :class="i <= pwdScore ? strengthColor : 'bg-ink-100'"></div>
        </div>
        <div class="mt-1 text-[11px] text-ink-500">强度：{{ strengthLabel }}</div>
      </div>
      <div class="mt-4 flex justify-end"><button class="btn-primary" @click="changePassword">修改密码</button></div>
    </div>

    <!-- #98 免打扰时段 -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">通知免打扰时段</h2>
      <p class="mt-1 text-[12px] text-ink-500">在此时间段内新通知不会弹出提醒（仍可在通知列表查看）。留空则关闭免打扰。</p>
      <div class="mt-3 flex items-center gap-3">
        <input v-model="form.dnd_start" type="time" class="input w-32" />
        <span class="text-ink-400">至</span>
        <input v-model="form.dnd_end" type="time" class="input w-32" />
        <button class="btn-outline text-[12px]" @click="saveDND">保存</button>
      </div>
    </div>

    <div class="card p-5">
      <div class="mb-2 flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">登录历史（安全日志）</h2>
        <button class="text-[12px] text-brand-600" @click="loadHistory">刷新</button>
      </div>
      <div class="divide-y divide-ink-50">
        <div v-for="h in history" :key="h.id" class="flex items-center justify-between py-2 text-[12px] text-ink-600">
          <span>{{ h.ip || '未知 IP' }} · {{ h.device || '未知设备' }}</span>
          <span class="text-ink-400">{{ formatTime(h.created_at) }}<span v-if="h.is_success" class="ml-1 text-emerald-500">成功</span></span>
        </div>
        <div v-if="!history.length" class="py-4 text-center text-[12px] text-ink-400">暂无记录</div>
      </div>
    </div>

    <!-- #56 登录设备管理 -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">登录设备管理</h2>
      <div class="mt-3 space-y-2">
        <div v-for="s in sessions" :key="s.id" class="flex items-center justify-between rounded-control border border-ink-100 px-3 py-2">
          <div>
            <div class="text-[13px]">{{ s.device || '未知设备' }}</div>
            <div class="text-[11px] text-ink-400">{{ s.ip || '' }} · 登录于 {{ formatTime(s.created_at) }}</div>
          </div>
          <button v-if="!s.is_revoked" class="btn-ghost text-[12px] text-rose-500" @click="revokeSession(s)">踢出</button>
        </div>
        <div v-if="!sessions.length" class="py-4 text-center text-[12px] text-ink-400">暂无活跃设备</div>
      </div>
    </div>

    <!-- #52 邀请码 + F625 邀请效果看板 -->
    <div class="card p-5">
      <div class="mb-2 flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">我的邀请码与邀请效果</h2>
        <button class="btn-primary text-[12px]" @click="genInvite">生成邀请码</button>
      </div>
      <!-- F625 看板：总量 + 每码使用/注册 + 近 30 天趋势 -->
      <div class="mb-3 grid grid-cols-4 gap-2 text-center">
        <div class="rounded-control bg-ink-50 py-2">
          <div class="text-[15px] font-bold">{{ inviteDash.totals?.codes ?? 0 }}</div>
          <div class="text-[10px] text-ink-400">邀请码</div>
        </div>
        <div class="rounded-control bg-ink-50 py-2">
          <div class="text-[15px] font-bold">{{ inviteDash.totals?.uses ?? 0 }}</div>
          <div class="text-[10px] text-ink-400">被使用</div>
        </div>
        <div class="rounded-control bg-ink-50 py-2">
          <div class="text-[15px] font-bold">{{ inviteDash.totals?.registrations ?? 0 }}</div>
          <div class="text-[10px] text-ink-400">带来注册</div>
        </div>
        <div class="rounded-control bg-ink-50 py-2">
          <div class="text-[15px] font-bold">{{ inviteDash.totals?.active_users ?? 0 }}</div>
          <div class="text-[10px] text-ink-400">仍活跃</div>
        </div>
      </div>
      <div v-if="(inviteDash.trend || []).some((t) => t.count > 0)" class="mb-3">
        <div class="mb-1 flex items-end gap-px" style="height: 44px">
          <div v-for="t in inviteDash.trend" :key="t.date" class="flex-1 rounded-t bg-brand-300"
               :style="{ height: Math.max(3, (t.count / maxInviteTrend) * 40) + 'px' }"
               :title="`${t.date}: ${t.count} 人注册`"></div>
        </div>
        <div class="text-[10px] text-ink-400">近 30 天邀请注册趋势</div>
      </div>
      <div class="mt-2 space-y-2">
        <div v-for="ic in invites" :key="ic.id" class="rounded-control border border-ink-100 px-3 py-2">
          <div class="flex items-center justify-between">
            <div>
              <code class="text-[13px] font-mono">{{ ic.code }}</code>
              <span class="ml-2 text-[11px]" :class="ic.is_valid ? 'text-emerald-500' : 'text-ink-400'">
                {{ ic.is_valid ? '有效' : '已用完/过期' }}
              </span>
            </div>
            <span class="text-[11px] text-ink-400">{{ ic.uses }}/{{ ic.max_uses }} 次</span>
          </div>
          <div class="mt-1 flex items-center gap-3 text-[11px] text-ink-500">
            <span>注册 <b class="text-ink-700">{{ dashOf(ic.code).registrations }}</b></span>
            <span>活跃 <b class="text-ink-700">{{ dashOf(ic.code).active_users }}</b></span>
            <span>转化 <b class="text-ink-700">{{ dashOf(ic.code).conversion }}%</b></span>
          </div>
        </div>
        <div v-if="!invites.length" class="py-4 text-center text-[12px] text-ink-400">暂无邀请码，点击上方按钮生成</div>
      </div>
    </div>

    <!-- #57 主题切换 -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">外观主题</h2>
      <div class="mt-3 flex gap-2">
        <button v-for="t in themes" :key="t.value" class="btn-outline text-[12px]"
                :class="theme === t.value ? 'border-brand-400 bg-brand-50 text-brand-700' : ''"
                @click="setTheme(t.value)">{{ t.label }}</button>
      </div>
    </div>

    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">账号与数据</h2>
      <div class="mt-3 flex flex-wrap gap-2">
        <button class="btn-outline text-[12px]" @click="exportData">导出我的数据（JSON · {{ exportCount ?? '--' }} 个模块）</button>
        <span class="tag">存储配额 {{ user.profile?.storage_quota_mb || 512 }} MB</span>
        <!-- F614 注销申请（7 天冷静期，可撤销） -->
        <button class="btn-outline text-[12px]" @click="requestDeactivate">申请注销（7 天冷静期）</button>
        <button class="btn-danger ml-auto text-[12px]" @click="deactivate">立即注销</button>
      </div>
      <div v-if="deact.status !== 'none'" class="mt-3 rounded-control px-3 py-2 text-[12px]"
           :class="deact.status === 'pending' ? 'bg-amber-50 text-amber-700' : 'bg-ink-50 text-ink-500'">
        <template v-if="deact.status === 'pending'">
          ⏳ 注销申请已提交：{{ formatTime(deact.execute_at) }} 执行（冷静期 {{ deact.cooldown_days }} 天，还剩约
          {{ deact.days_left }} 天）。冷静期内账号可正常使用。
          <button class="ml-2 font-medium text-emerald-600 hover:underline" @click="cancelDeactivate">撤销申请</button>
        </template>
        <template v-else-if="deact.status === 'cancelled'">已撤销注销申请（账号正常）</template>
        <template v-else>注销申请已执行，账号已停用</template>
      </div>
      <div class="mt-3 flex flex-wrap gap-1.5">
        <span v-for="r in user.permissions" :key="r" class="tag tag-brand font-mono">{{ r }}</span>
      </div>
    </div>

    <!-- ================= F616 安全评分卡 ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">安全评分卡</h2>
        <button class="text-[12px] text-brand-600" @click="loadSecurity">重新评估</button>
      </div>
      <div v-if="security.items" class="mt-3 flex items-center gap-5">
        <div class="relative h-24 w-24 shrink-0">
          <svg viewBox="0 0 100 100" class="h-24 w-24 -rotate-90">
            <circle cx="50" cy="50" r="42" fill="none" stroke="#e5e7eb" stroke-width="10" />
            <circle cx="50" cy="50" r="42" fill="none" :stroke="scoreColor" stroke-width="10"
                    stroke-linecap="round" :stroke-dasharray="264" :stroke-dashoffset="264 - 264 * security.score / 100" />
          </svg>
          <div class="absolute inset-0 grid place-items-center">
            <div class="text-center">
              <div class="text-[22px] font-bold text-ink-900">{{ security.score }}</div>
              <div class="text-[10px] text-ink-400">{{ security.grade }}</div>
            </div>
          </div>
        </div>
        <div class="flex-1 space-y-1.5">
          <div v-for="it in security.items" :key="it.key" class="flex items-center gap-2 text-[12px]">
            <span :class="it.passed ? 'text-emerald-500' : 'text-ink-300'">{{ it.passed ? '✔' : '○' }}</span>
            <span class="flex-1" :class="it.passed ? 'text-ink-600' : 'text-ink-400'">{{ it.label }}</span>
            <span class="text-ink-300">{{ it.weight }} 分</span>
          </div>
        </div>
      </div>
      <div v-if="(security.tips || []).length" class="mt-3 rounded-control bg-amber-50 px-3 py-2 text-[11px] text-amber-700">
        建议：{{ security.tips[0] }}
      </div>
      <div v-else-if="security.items" class="mt-3 rounded-control bg-emerald-50 px-3 py-2 text-[11px] text-emerald-700">
        所有安全项均已达成，保持得不错！
      </div>
    </div>

    <!-- ================= F615 TOTP 双因素 ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">两步验证（TOTP）</h2>
        <span class="tag" :class="totp.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
          {{ totp.enabled ? '已开启' : '未开启' }}
        </span>
      </div>
      <p class="mt-1 text-[12px] text-ink-500">开启后，登录时除密码外还需输入验证器 App 的 6 位动态口令（标准 RFC 6238，纯后端标准库实现）。</p>

      <div v-if="!totp.configured" class="mt-3">
        <button class="btn-primary text-[12px]" :disabled="totpBusy" @click="setupTotp">生成密钥并绑定</button>
      </div>
      <div v-else class="mt-3 space-y-3">
        <div class="rounded-control border border-ink-100 bg-ink-50/60 p-3">
          <div class="text-[11px] text-ink-500">Base32 密钥（可复制到验证器 App 手动录入）</div>
          <div class="mt-1 flex items-center gap-2">
            <code class="flex-1 break-all font-mono text-[13px] tracking-wider text-ink-800">{{ totp.secret }}</code>
            <button class="btn-outline shrink-0 text-[12px]" @click="copyText(totp.secret, '密钥已复制')">复制</button>
          </div>
          <div class="mt-2 flex items-center gap-2">
            <span class="text-[11px] text-ink-500">otpauth 链接</span>
            <button class="btn-ghost text-[12px]" @click="copyText(totp.otpauth_url, '链接已复制')">复制链接</button>
            <span class="text-[11px] text-ink-400">{{ totp.digits }} 位 / {{ totp.period }} 秒 / {{ totp.algorithm }}</span>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <input v-model="totpCode" class="input w-40 tracking-[0.3em]" maxlength="6" inputmode="numeric" placeholder="6 位验证码" />
          <button v-if="!totp.enabled" class="btn-primary text-[12px]" :disabled="totpBusy || totpCode.length < 6"
                  @click="enableTotp">确认开启</button>
          <template v-else>
            <button class="btn-danger text-[12px]" :disabled="totpBusy || totpCode.length < 6" @click="disableTotp">关闭验证</button>
            <button class="btn-ghost text-[12px]" @click="setupTotp">重新生成密钥</button>
          </template>
        </div>
        <div v-if="totp.last_used_at" class="text-[11px] text-ink-400">最近校验：{{ formatTime(totp.last_used_at) }}</div>
      </div>
    </div>

    <!-- ================= F619 新手任务清单 ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">新手任务清单</h2>
        <span class="text-[12px] text-ink-400">{{ onboarding.done_count || 0 }}/{{ onboarding.total_count || 6 }} 已完成</span>
      </div>
      <div class="mt-2 h-2 rounded-full bg-ink-100">
        <div class="h-2 rounded-full bg-brand-500 transition-all" :style="{ width: (onboarding.progress || 0) + '%' }"></div>
      </div>
      <div class="mt-3 space-y-2">
        <div v-for="(s, i) in onboarding.steps || []" :key="s.key"
             class="flex items-center gap-3 rounded-control border px-3 py-2"
             :class="s.done ? 'border-emerald-100 bg-emerald-50/50' : 'border-ink-100'">
          <span class="grid h-6 w-6 place-items-center rounded-full text-[11px]"
                :class="s.done ? 'bg-emerald-500 text-white' : 'bg-ink-100 text-ink-500'">{{ s.done ? '✓' : i + 1 }}</span>
          <div class="flex-1">
            <div class="text-[13px]" :class="s.done ? 'text-ink-400 line-through' : 'text-ink-700'">{{ s.title }}</div>
            <div class="text-[11px] text-ink-400">{{ s.desc }}</div>
          </div>
          <button v-if="!s.done" class="btn-ghost text-[12px] text-brand-600" @click="$router.push(s.link)">去完成</button>
          <span v-else class="text-[11px] text-emerald-500">已完成</span>
        </div>
      </div>
      <div v-if="onboarding.all_done" class="mt-2 rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
        🎉 六步全部完成，你已经是平台老手了！
      </div>
    </div>

    <!-- ================= F620 时区与周起始日偏好 ================= -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">时区与周起始日</h2>
      <p class="mt-1 text-[12px] text-ink-500">影响日程、看板与统计里「一周从哪天开始」以及时间显示口径。</p>
      <div class="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-[12px] font-medium text-ink-600">时区</label>
          <select v-model="pref.timezone" class="input">
            <option v-for="tz in pref.timezones" :key="tz" :value="tz">{{ tz }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-[12px] font-medium text-ink-600">周起始日</label>
          <div class="flex gap-2">
            <button v-for="w in pref.weekChoices" :key="w.value" class="btn-outline text-[12px]"
                    :class="pref.week_start === w.value ? 'border-brand-400 bg-brand-50 text-brand-700' : ''"
                    @click="pref.week_start = w.value">{{ w.label }}</button>
          </div>
        </div>
      </div>
      <div class="mt-3 flex justify-end"><button class="btn-primary text-[12px]" @click="savePrefs">保存偏好</button></div>
    </div>

    <!-- ================= F617 个人公开主页预览 + F618 关注/粉丝 ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">个人公开主页</h2>
        <button class="btn-outline text-[12px]" @click="openMyProfile">打开 /u/{{ user.profile?.username }}</button>
      </div>
      <div class="mt-3 flex items-center gap-3 rounded-control border border-ink-100 p-3">
        <img v-if="pubSelf?.avatar" :src="pubSelf.avatar" class="h-12 w-12 rounded-full object-cover" />
        <div v-else class="grid h-12 w-12 place-items-center rounded-full bg-brand-100 font-bold text-brand-700">{{ user.displayName.slice(0, 1) }}</div>
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-ink-800">{{ pubSelf?.display_name || user.displayName }}</div>
          <div class="truncate text-[11px] text-ink-400">{{ pubSelf?.bio || '还没有简介' }}</div>
        </div>
        <button class="btn-ghost shrink-0 text-[12px]" @click="copyProfileLink">复制链接</button>
      </div>
      <div class="mt-2 text-[11px] text-ink-400">
        公开字段：昵称 / 简介 / 标签 / 部门 / 徽章 / 计数；密码、邮箱、手机号等不会公开。
      </div>
      <div class="mt-4 grid grid-cols-2 gap-3">
        <div class="rounded-control bg-ink-50 px-3 py-2 text-center">
          <div class="text-[16px] font-bold">{{ follows.followers_count ?? 0 }}</div>
          <div class="text-[11px] text-ink-400">粉丝</div>
        </div>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-center">
          <div class="text-[16px] font-bold">{{ follows.following_count ?? 0 }}</div>
          <div class="text-[11px] text-ink-400">关注</div>
        </div>
      </div>
      <div class="mt-3 flex gap-2">
        <button class="btn-outline text-[12px]" :class="followTab === 'following' ? 'border-brand-400 bg-brand-50' : ''"
                @click="loadFollows('following')">我的关注</button>
        <button class="btn-outline text-[12px]" :class="followTab === 'followers' ? 'border-brand-400 bg-brand-50' : ''"
                @click="loadFollows('followers')">我的粉丝</button>
      </div>
      <div v-if="(follows.list || []).length" class="mt-2 space-y-1.5">
        <div v-for="f in follows.list" :key="f.id" class="flex items-center gap-2 rounded-control border border-ink-100 px-3 py-1.5">
          <img v-if="f.avatar" :src="f.avatar" class="h-7 w-7 rounded-full object-cover" />
          <div v-else class="grid h-7 w-7 place-items-center rounded-full bg-brand-100 text-[11px] font-bold text-brand-700">{{ f.display_name.slice(0, 1) }}</div>
          <span class="text-[13px]">{{ f.display_name }}</span>
          <span class="text-[11px] text-ink-400">@{{ f.username }}</span>
          <button class="btn-ghost ml-auto text-[12px] text-brand-600" @click="$router.push('/u/' + f.username)">主页</button>
        </div>
      </div>
      <div v-else class="mt-2 py-3 text-center text-[12px] text-ink-400">暂无数据，去别人主页点「关注」试试</div>
    </div>

    <!-- ================= F621 长期访问令牌 PAT ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">长期访问令牌（PAT）</h2>
        <button class="btn-primary text-[12px]" @click="createToken">＋ 新建令牌</button>
      </div>
      <p class="mt-1 text-[12px] text-ink-500">
        供脚本/CI 调用接口：在请求头带 <code class="font-mono">Authorization: Bearer pat_xxx</code> 或
        <code class="font-mono">X-Api-Token: pat_xxx</code>。令牌只在创建时显示一次。
      </p>
      <div v-if="newToken" class="mt-2 rounded-control border border-amber-200 bg-amber-50 p-3">
        <div class="text-[11px] text-amber-700">请立即复制保存（仅显示一次）：</div>
        <code class="mt-1 block break-all font-mono text-[12px] text-ink-800">{{ newToken }}</code>
        <div class="mt-2 flex gap-2">
          <button class="btn-outline text-[12px]" @click="copyText(newToken, '令牌已复制')">复制令牌</button>
          <button class="btn-ghost text-[12px]" @click="newToken = ''">我已保存</button>
        </div>
      </div>
      <div class="mt-3 space-y-2">
        <div v-for="t in pat.list" :key="t.id" class="flex items-center justify-between rounded-control border border-ink-100 px-3 py-2">
          <div>
            <div class="text-[13px]">{{ t.name }} <span class="font-mono text-[11px] text-ink-400">{{ t.prefix }}</span></div>
            <div class="text-[11px] text-ink-400">
              {{ t.expires_at ? '到期 ' + formatTime(t.expires_at) : '长期有效' }}
              <span v-if="t.last_used_at">· 最近使用 {{ formatTime(t.last_used_at) }}</span>
            </div>
          </div>
          <button v-if="t.is_valid" class="btn-ghost text-[12px] text-rose-500" @click="revokeToken(t)">吊销</button>
          <span v-else class="text-[11px] text-ink-400">已吊销/过期</span>
        </div>
        <div v-if="!pat.list.length" class="py-3 text-center text-[12px] text-ink-400">暂无令牌</div>
      </div>
    </div>

    <!-- ================= F624 通讯录备注名（仅自己可见） ================= -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">通讯录备注名</h2>
      <p class="mt-1 text-[12px] text-ink-500">仅你自己可见，不会影响对方的展示名。</p>
      <div class="mt-3 flex gap-2">
        <input v-model="contactForm.username" class="input w-36" placeholder="对方用户名" />
        <input v-model="contactForm.alias" class="input flex-1" placeholder="备注名，如「产品-王老师」" @keyup.enter="saveContact" />
        <button class="btn-outline text-[12px]" @click="saveContact">保存</button>
      </div>
      <div class="mt-3 space-y-1.5">
        <div v-for="c in contacts" :key="c.id" class="flex items-center gap-2 rounded-control border border-ink-100 px-3 py-1.5">
          <img v-if="c.avatar" :src="c.avatar" class="h-7 w-7 rounded-full object-cover" />
          <div v-else class="grid h-7 w-7 place-items-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700">{{ c.alias.slice(0, 1) }}</div>
          <span class="text-[13px]">{{ c.alias }}</span>
          <span class="text-[11px] text-ink-400">@{{ c.username }}（{{ c.display_name }}）</span>
          <button class="btn-ghost ml-auto text-[12px] text-rose-500" @click="deleteContact(c)">删除</button>
        </div>
        <div v-if="!contacts.length" class="py-3 text-center text-[12px] text-ink-400">还没有备注</div>
      </div>
    </div>

    <!-- ================= F623 头像历史切换 ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">头像历史</h2>
        <button class="text-[12px] text-brand-600" @click="loadAvatarHistory">刷新</button>
      </div>
      <p class="mt-1 text-[12px] text-ink-500">每次上传/移除头像都会自动留存旧头像，可一键切换回去（最多保留 10 张）。</p>
      <div class="mt-3 flex flex-wrap gap-3">
        <div v-for="a in avatarHistory" :key="a.id" class="w-20 text-center">
          <img :src="a.image" class="h-16 w-16 rounded-full border border-ink-100 object-cover" />
          <div class="mt-1 text-[10px] text-ink-400">{{ (a.created_at || '').slice(5, 10) }}</div>
          <button v-if="!a.is_current" class="btn-ghost w-full text-[11px] text-brand-600" @click="restoreAvatar(a)">切回</button>
          <div v-else class="text-[10px] text-emerald-500">当前</div>
        </div>
        <div v-if="!avatarHistory.length" class="py-4 text-[12px] text-ink-400">暂无历史头像</div>
      </div>
    </div>

    <!-- ================= F622 昵称变更历史 ================= -->
    <div class="card p-5">
      <div class="flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">昵称变更历史</h2>
        <span class="text-[11px] text-ink-400">共 {{ nickHistory.length }} 条</span>
      </div>
      <div v-if="nickHistory.length" class="mt-2 divide-y divide-ink-50">
        <div v-for="n in nickHistory" :key="n.id" class="flex items-center justify-between py-2 text-[12px]">
          <span class="text-ink-600">
            <span v-if="n.old_value" class="text-ink-400">{{ n.old_value }}</span>
            <span v-else class="text-ink-300">（空）</span>
            <span class="mx-1.5 text-ink-300">→</span>{{ n.new_value || '（空）' }}
          </span>
          <span class="text-ink-400">{{ formatTime(n.changed_at) }}</span>
        </div>
      </div>
      <div v-else class="py-3 text-center text-[12px] text-ink-400">还没有改过昵称</div>
    </div>

    <!-- ================= F642 关于平台 ================= -->
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">关于平台</h2>
      <div class="mt-3 grid gap-2 text-[12px] sm:grid-cols-2">
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-500">版本</span><span class="font-medium">{{ about.version || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-500">运行时长</span><span class="font-medium">{{ about.runtime?.uptime_text || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-500">Python / Django</span>
          <span class="font-medium">{{ about.runtime?.python || '-' }} / {{ about.runtime?.django || '-' }}</span>
        </div>
        <div class="flex justify-between rounded-control bg-ink-50 px-3 py-2">
          <span class="text-ink-500">最近提交</span>
          <span v-if="about.git?.available" class="font-mono font-medium">{{ about.git.hash }} · {{ about.git.date }}</span>
          <span v-else class="text-ink-400">暂无（{{ about.git?.reason || '不可用' }}）</span>
        </div>
      </div>
      <div v-if="about.git?.available" class="mt-2 truncate text-[11px] text-ink-400">{{ about.git.subject }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '../api'
import { authxApi } from '../api/authx'
import { corexApi, reportLatencySamples } from '../api/corex'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { formatTime } from '../utils/format'

const user = useUserStore()
const app = useAppStore()
const router = useRouter()
const route = useRoute()
const avatarInput = ref(null)
const username = ref('')
const exportCount = ref(null)
const form = reactive({ nickname: '', email: '', phone: '', bio: '', tags: [], dnd_start: '', dnd_end: '' })
const tagsInput = ref('')
const pwd = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdScore = ref(0)
const history = ref([])
const badges = ref([])
const invites = ref([])
const sessions = ref([])
const theme = ref(localStorage.getItem('theme') || 'system')
const themes = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]

// #54 头像裁剪
const cropModal = ref(false)
const cropImage = ref(null)
const avatarPreview = ref('')
const cropCanvas = ref(null)

const strengthLabel = computed(() => ['', '弱', '一般', '中等', '强', '很强'][pwdScore.value])
const strengthColor = computed(() => ['', 'bg-rose-400', 'bg-amber-400', 'bg-amber-400', 'bg-emerald-400', 'bg-emerald-500'][pwdScore.value])

// #50 密码强度检测（前端计算，与 minitools 逻辑一致）
function checkPwdStrength() {
  const p = pwd.new_password
  if (!p) { pwdScore.value = 0; return }
  let s = 0
  if (p.length >= 8) s++
  if (/[A-Z]/.test(p)) s++
  if (/[a-z]/.test(p)) s++
  if (/\d/.test(p)) s++
  if (/[^A-Za-z0-9]/.test(p)) s++
  pwdScore.value = s
}

async function loadProfile() {
  await user.fetchProfile()
  const p = user.profile || {}
  username.value = p.username || ''
  Object.assign(form, {
    nickname: p.nickname || '', email: p.email || '', phone: p.phone || '', bio: p.bio || '',
    dnd_start: p.dnd_start || '', dnd_end: p.dnd_end || '',
  })
  tagsInput.value = (p.tags || []).join(', ')
}
async function loadHistory() {
  history.value = (await authApi.loginHistory()).list || []
}
async function loadBadges() {
  badges.value = (await authApi.badges()).list || []
}
async function loadInvites() {
  invites.value = (await authApi.invites()).list || []
}
async function loadSessions() {
  sessions.value = (await authApi.sessions()).list || []
}

async function saveProfile() {
  form.tags = tagsInput.value.split(/[,，]/).map(t => t.trim()).filter(Boolean)
  await authApi.updateProfile(form)
  await user.fetchProfile()
  app.toastMsg('资料已保存', 'success')
}
async function saveDND() {
  await authApi.updateProfile({ dnd_start: form.dnd_start || null, dnd_end: form.dnd_end || null })
  app.toastMsg('免打扰设置已保存', 'success')
}
async function saveUsername() {
  await authApi.changeUsername(username.value.trim())
  await loadProfile()
  app.toastMsg('用户名已修改', 'success')
}

// #54 头像裁剪
function onAvatarSelect(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => {
    cropImage.value = ev.target.result
    cropModal.value = true
    setTimeout(drawCropCanvas, 100)
  }
  reader.readAsDataURL(file)
  e.target.value = ''
}
function drawCropCanvas() {
  const canvas = cropCanvas.value
  if (!canvas || !cropImage.value) return
  const ctx = canvas.getContext('2d')
  const img = new Image()
  img.onload = () => {
    const size = Math.min(img.width, img.height)
    const sx = (img.width - size) / 2
    const sy = (img.height - size) / 2
    ctx.drawImage(img, sx, sy, size, size, 0, 0, 200, 200)
  }
  img.src = cropImage.value
}
async function doCropAndUpload() {
  const canvas = cropCanvas.value
  if (!canvas) return
  canvas.toBlob(async (blob) => {
    const fd = new FormData()
    fd.append('avatar', blob, 'avatar.png')
    await authApi.uploadAvatar(fd)
    await user.fetchProfile()
    cropModal.value = false
    app.toastMsg('头像已更新', 'success')
  }, 'image/png')
}

async function removeAvatar() {
  await authApi.deleteAvatar()
  await user.fetchProfile()
}
async function changePassword() {
  if (pwd.new_password !== pwd.confirm) return app.toastMsg('两次密码不一致', 'error')
  await authApi.changePassword({ old_password: pwd.old_password, new_password: pwd.new_password })
  app.toastMsg('密码已修改，请重新登录', 'success')
  setTimeout(async () => { await user.logout(); router.push('/login') }, 1200)
}

// #52 邀请码
async function genInvite() {
  await authApi.createInvite({ max_uses: 1, expires_days: 30 })
  loadInvites()
  loadInviteDashboard()
  app.toastMsg('邀请码已生成', 'success')
}

// F625 邀请效果看板
const inviteDash = ref({ codes: [], totals: {}, trend: [] })
const maxInviteTrend = computed(() => Math.max(1, ...(inviteDash.value.trend || []).map((t) => t.count)))
function dashOf(code) {
  return (inviteDash.value.codes || []).find((c) => c.code === code) || { registrations: 0, active_users: 0, conversion: 0 }
}
async function loadInviteDashboard() {
  try { inviteDash.value = await authxApi.inviteDashboard() } catch (e) { inviteDash.value = { codes: [], totals: {}, trend: [] } }
}

// #56 会话管理
async function revokeSession(s) {
  await authApi.revokeSession(s.id)
  loadSessions()
  app.toastMsg('已踢出该设备', 'success')
}

// #57 主题
function setTheme(t) {
  theme.value = t
  localStorage.setItem('theme', t)
  const root = document.documentElement
  if (t === 'dark' || (t === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

async function exportData() {
  const data = await authApi.exportData()
  exportCount.value = Math.max(1, Object.keys(data || {}).length - 3)
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'my-data.json'; a.click()
  URL.revokeObjectURL(url)
}
// F13：模块数改为动态获取（与导出同一接口/公式，初始 null 显示 "--"，失败静默）
async function loadExportCount() {
  try {
    const data = await authApi.exportData()
    exportCount.value = Math.max(1, Object.keys(data || {}).length - 3)
  } catch { /* 接口失败时保持 null，按钮显示 -- */ }
}
async function deactivate() {
  const pw = prompt('注销后账号将被禁用，如需继续请输入登录密码：')
  if (pw === null) return
  await authApi.deactivate(pw)
  app.toastMsg('账号已注销', 'success')
  await user.logout()
  router.push('/login')
}

// ===========================================================================
// v8 新增（F613–F626 + F642 关于页）
// ===========================================================================

function copyText(text, msg) {
  const done = () => app.toastMsg(msg || '已复制', 'success')
  const fallback = () => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy'); done() } catch (e) { app.toastMsg('复制失败，请手动复制', 'error') }
    document.body.removeChild(ta)
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(fallback)
  } else {
    fallback()
  }
}

const myProfileUrl = () => `${window.location.origin}/u/${user.profile?.username || ''}`
function copyProfileLink() { copyText(myProfileUrl(), '主页链接已复制') }
function openMyProfile() {
  if (user.profile?.username) router.push(`/u/${user.profile.username}`)
}

// ---------------- F617 公开主页 ----------------
const pub = ref(null)
const pubLoading = ref(false)
const pubError = ref('')
const followBusy = ref(false)
const publicMode = computed(() => route.name === 'public-profile' && !!route.params.username)

async function loadPublicProfile() {
  pubLoading.value = true
  pubError.value = ''
  try {
    pub.value = await authxApi.publicProfile(route.params.username)
  } catch (e) {
    pub.value = null
    pubError.value = e.message || '用户不存在'
  } finally {
    pubLoading.value = false
  }
}

// F26：/u/a → /u/b 是同一条路由换 params，组件被复用不会重新挂载，必须监听参数变化重拉
watch(
  () => route.params.username,
  (name, prev) => {
    if (!publicMode.value || !name || name === prev) return
    pub.value = null
    pubError.value = ''
    followBusy.value = false
    loadPublicProfile()
  }
)

async function toggleFollowPub() {
  if (!pub.value) return
  if (!user.loggedIn) { router.push('/login'); return }
  followBusy.value = true
  try {
    const r = await authxApi.followToggle(pub.value.username)
    pub.value.is_following = r.following
    if (pub.value.stats) {
      pub.value.stats.followers = r.followers_count
      pub.value.stats.following = r.following_count
    }
    app.toastMsg(r.following ? '已关注' : '已取消关注', 'success')
  } catch (e) {
    app.toastMsg(e.message || '操作失败', 'error')
  } finally {
    followBusy.value = false
  }
}
function goHome() { router.push(user.loggedIn ? '/dashboard' : '/login') }

// ---------------- F616 安全评分卡 ----------------
const security = ref({})
const scoreColor = computed(() => {
  const s = security.value.score || 0
  return s >= 75 ? '#10b981' : s >= 60 ? '#f59e0b' : '#ef4444'
})
async function loadSecurity() {
  try { security.value = await authxApi.securityScore() } catch (e) { security.value = {} }
}

// ---------------- F615 TOTP ----------------
const totp = ref({ enabled: false, configured: false, secret: '', otpauth_url: '', digits: 6, period: 30, algorithm: 'SHA1' })
const totpCode = ref('')
const totpBusy = ref(false)
async function loadTotp() {
  try { totp.value = await authxApi.totpStatus() } catch (e) { /* ignore */ }
}
async function setupTotp() {
  totpBusy.value = true
  try {
    const r = await authxApi.totpSetup()
    totp.value = { ...totp.value, ...r, configured: true }
    totpCode.value = ''
    app.toastMsg('密钥已生成，请复制到验证器 App 后提交验证码', 'info')
  } catch (e) { app.toastMsg(e.message || '生成失败', 'error') } finally { totpBusy.value = false }
}
async function enableTotp() {
  totpBusy.value = true
  try {
    await authxApi.totpVerify({ mode: 'enable', code: totpCode.value })
    totpCode.value = ''
    await loadTotp()
    app.toastMsg('两步验证已开启', 'success')
  } catch (e) { app.toastMsg(e.message || '验证码错误', 'error') } finally { totpBusy.value = false }
}
async function disableTotp() {
  totpBusy.value = true
  try {
    await authxApi.totpVerify({ mode: 'disable', code: totpCode.value })
    totpCode.value = ''
    await loadTotp()
    app.toastMsg('两步验证已关闭', 'success')
  } catch (e) { app.toastMsg(e.message || '验证码错误', 'error') } finally { totpBusy.value = false }
}

// ---------------- F619 新手任务清单 ----------------
const onboarding = ref({})
async function loadOnboarding() {
  try { onboarding.value = await authxApi.onboarding() } catch (e) { onboarding.value = {} }
}

// ---------------- F620 时区与周起始日 ----------------
const pref = reactive({ timezone: 'Asia/Shanghai', week_start: 'mon', timezones: [], weekChoices: [] })
async function loadPrefs() {
  try {
    const r = await authxApi.preferences()
    pref.timezone = r.timezone || 'Asia/Shanghai'
    pref.week_start = r.week_start || 'mon'
    pref.timezones = r.common_timezones || []
    pref.weekChoices = r.week_start_choices || []
  } catch (e) { /* ignore */ }
}
async function savePrefs() {
  try {
    await authxApi.savePreferences({ timezone: pref.timezone, week_start: pref.week_start })
    app.toastMsg('偏好已保存', 'success')
  } catch (e) { app.toastMsg(e.message || '保存失败', 'error') }
}

// ---------------- F618 关注 / 粉丝 ----------------
const follows = ref({})
const followTab = ref('following')
async function loadFollows(type = 'following') {
  followTab.value = type
  try { follows.value = await authxApi.followList(type) } catch (e) { follows.value = {} }
}

// ---------------- F621 PAT ----------------
const pat = ref({ list: [] })
const newToken = ref('')
async function loadTokens() {
  try { pat.value = await authxApi.tokens() } catch (e) { pat.value = { list: [] } }
}
async function createToken() {
  const name = prompt('令牌名称（如 ci-script / local-dev）：', 'script')
  if (!name) return
  try {
    const r = await authxApi.createToken({ name, expires_days: 90 })
    newToken.value = r.token
    await loadTokens()
    app.toastMsg('令牌已创建，请立即复制', 'success')
  } catch (e) { app.toastMsg(e.message || '创建失败', 'error') }
}
async function revokeToken(t) {
  if (!confirm(`确定吊销令牌「${t.name}」？吊销后脚本将立即失效。`)) return
  try {
    await authxApi.revokeToken(t.id)
    await loadTokens()
    app.toastMsg('令牌已吊销', 'success')
  } catch (e) { app.toastMsg(e.message || '吊销失败', 'error') }
}

// ---------------- F624 通讯录备注名 ----------------
const contacts = ref([])
const contactForm = reactive({ username: '', alias: '' })
async function loadContacts() {
  try { contacts.value = (await authxApi.contacts()).list || [] } catch (e) { contacts.value = [] }
}
async function saveContact() {
  if (!contactForm.username.trim() || !contactForm.alias.trim()) return app.toastMsg('请填写用户名与备注名', 'error')
  try {
    await authxApi.saveContact({ username: contactForm.username.trim(), alias: contactForm.alias.trim() })
    contactForm.username = ''
    contactForm.alias = ''
    await loadContacts()
    app.toastMsg('备注已保存（仅自己可见）', 'success')
  } catch (e) { app.toastMsg(e.message || '保存失败', 'error') }
}
async function deleteContact(c) {
  try {
    await authxApi.deleteContact(c.id)
    await loadContacts()
  } catch (e) { app.toastMsg(e.message || '删除失败', 'error') }
}

// ---------------- F623 头像历史 ----------------
const avatarHistory = ref([])
async function loadAvatarHistory() {
  try { avatarHistory.value = (await authxApi.avatarHistory()).list || [] } catch (e) { avatarHistory.value = [] }
}
async function restoreAvatar(a) {
  try {
    await authxApi.restoreAvatar(a.id)
    await user.fetchProfile()
    await loadAvatarHistory()
    app.toastMsg('已切换为历史头像', 'success')
  } catch (e) { app.toastMsg(e.message || '切换失败', 'error') }
}

// ---------------- F622 昵称变更历史 ----------------
const nickHistory = ref([])
async function loadNicknameHistory() {
  try { nickHistory.value = (await authxApi.nicknameHistory()).list || [] } catch (e) { nickHistory.value = [] }
}

// ---------------- F614 注销冷静期 ----------------
const deact = ref({ status: 'none', cooldown_days: 7 })
async function loadDeactivate() {
  try { deact.value = await authxApi.deactivateState() } catch (e) { deact.value = { status: 'none' } }
}
async function requestDeactivate() {
  const pw = prompt(`申请注销后账号将在 ${deact.value.cooldown_days || 7} 天冷静期后停用（期间可撤销）。请输入登录密码确认：`)
  if (pw === null) return
  try {
    deact.value = await authxApi.requestDeactivate({ password: pw })
    app.toastMsg('注销申请已提交，7 天内可撤销', 'success')
  } catch (e) { app.toastMsg(e.message || '提交失败', 'error') }
}
async function cancelDeactivate() {
  try {
    deact.value = await authxApi.cancelDeactivate()
    app.toastMsg('注销申请已撤销', 'success')
  } catch (e) { app.toastMsg(e.message || '撤销失败', 'error') }
}

// ---------------- F642 关于平台 ----------------
const about = ref({})
async function loadAbout() {
  try { about.value = await corexApi.about() } catch (e) { about.value = {} }
}

async function loadSelfPublicCard() {
  try { pubSelf.value = await authxApi.publicProfile(user.profile?.username || route.params.username || '') } catch (e) { pubSelf.value = null }
}
const pubSelf = ref(null)

onMounted(() => {
  if (publicMode.value) {
    loadPublicProfile()
    return
  }
  loadProfile()
  loadHistory()
  loadBadges()
  loadInvites()
  loadSessions()
  loadSecurity()
  loadTotp()
  loadOnboarding()
  loadPrefs()
  loadFollows('following')
  loadExportCount()
  loadTokens()
  loadContacts()
  loadAvatarHistory()
  loadNicknameHistory()
  loadDeactivate()
  loadAbout()
  loadSelfPublicCard()
  loadInviteDashboard()
  // F632/F633：把 localStorage 里的接口耗时采样与运行时异常上报给后端（静默）
  reportLatencySamples()
})
</script>
