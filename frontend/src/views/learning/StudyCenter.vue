<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">我的学习</h2>
        <p class="text-[12px] text-ink-400">学习进度、代码收藏、专注打卡、学习计划与掌握度，全部云端保存</p>
      </div>
      <div class="flex flex-wrap gap-1 rounded-control bg-ink-100 p-1" role="tablist" aria-label="我的学习分区">
        <button v-for="(t, i) in tabs" :key="t.v" role="tab" :aria-selected="tab === t.v" :tabindex="tab === t.v ? 0 : -1"
          class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'"
          @click="switchTab(t.v)" @keydown="onTabKey($event, i)">{{ t.label }}</button>
      </div>
    </div>

    <!-- 学习概览（#83 #84 #85） -->
    <template v-if="tab === 'overview'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        一眼看清“最近学了没”：上面三张数字卡分别是今日 / 本周 / 本月累计分钟（数据来自「专注记录」的打卡）；
        中间 14 天柱状图按最大值归一，鼠标停在柱上看当天分钟；下面月历可前后翻，有记录的日子整块填深色——
        空白格多说明该去打卡了。
      </p>
      <div class="grid grid-cols-3 gap-3">
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ todayMin }}</div><div class="text-[12px] text-ink-400">今日(分钟)</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ weekMin }}</div><div class="text-[12px] text-ink-400">本周(分钟)</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ monthMin }}</div><div class="text-[12px] text-ink-400">本月(分钟)</div></div>
      </div>

      <!-- 378 考试倒计时 -->
      <div class="card p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">考试倒计时</h3>
          <span v-if="exams.nearest" class="tag bg-rose-50 text-rose-600">最近：{{ exams.nearest.title }}</span>
          <button class="btn-outline ml-auto px-2 py-0.5 text-[11px]" @click="loadExams">刷新</button>
        </div>
        <div v-if="exams.nearest" class="mb-2 flex flex-wrap items-center gap-4 rounded-control bg-brand-50 px-3 py-2">
          <div class="text-center">
            <div class="text-[24px] font-bold leading-none text-brand-700">{{ exams.nearest.days_left }}</div>
            <div class="mt-0.5 text-[11px] text-ink-400">天后考试</div>
          </div>
          <div class="text-[12px] leading-6 text-ink-600">
            <div class="text-[13px] font-medium text-ink-800">{{ exams.nearest.title }}<span class="text-ink-400"> · {{ exams.nearest.exam_date }}</span></div>
            <div v-if="exams.nearest.daily_questions">按剩余天数摊分，每天约 <b class="text-brand-700">{{ exams.nearest.daily_questions }}</b> 题{{ exams.nearest.subject ? '（' + exams.nearest.subject + '）' : '' }}</div>
            <div v-else class="text-ink-400">还没填目标题量：补一个数字就能算出每天要刷几题。</div>
          </div>
        </div>
        <div v-if="exams.list && exams.list.length" class="space-y-1">
          <div v-for="e in exams.list" :key="e.id" class="flex flex-wrap items-center gap-2 rounded-control bg-ink-50 px-2.5 py-1.5 text-[12px]">
            <span class="tag">{{ e.subject || '未填学科' }}</span>
            <span class="text-[13px] font-medium text-ink-800">{{ e.title }}</span>
            <span class="text-ink-400">{{ e.exam_date }}</span>
            <span :class="e.passed ? 'text-ink-400' : e.urgent ? 'font-medium text-rose-500' : 'text-brand-600'">
              {{ e.passed ? '已考完' : '还剩 ' + e.days_left + ' 天' }}
            </span>
            <span v-if="e.daily_questions" class="text-ink-500">每日 {{ e.daily_questions }} 题</span>
            <button class="btn-danger ml-auto px-2 py-0.5 text-[11px]" @click="delExam(e.id)">删除</button>
          </div>
        </div>
        <div v-else class="text-[12px] leading-6 text-ink-400">
          还没有考试：填名称和日期（可选学科、目标题量）点「添加」，卡片会按剩余天数摊出每天该刷多少题。
        </div>
        <div class="mt-2 grid grid-cols-12 gap-2">
          <input v-model="exf.title" class="input col-span-12 h-8 text-[12px] sm:col-span-4" placeholder="考试名称，如 期中数学" />
          <input v-model="exf.exam_date" type="date" class="input col-span-6 h-8 text-[12px] sm:col-span-3" />
          <input v-model="exf.subject" class="input col-span-6 h-8 text-[12px] sm:col-span-2" placeholder="学科" />
          <input v-model.number="exf.target_count" type="number" min="0" class="input col-span-4 h-8 text-[12px] sm:col-span-1" placeholder="题量" />
          <button class="btn-primary col-span-4 h-8 text-[12px] sm:col-span-2" @click="addExam">添加</button>
        </div>
      </div>

      <!-- 377 每日提醒 / 学习榜公开 -->
      <div class="card p-4">
        <div class="flex flex-wrap items-center gap-3">
          <h3 class="text-[14px] font-semibold text-ink-800">每日提醒</h3>
          <button class="tag cursor-pointer" :class="pref.daily_remind ? 'bg-brand-600 text-white' : ''" @click="togglePref('daily_remind')">
            {{ pref.daily_remind ? '已开启' : '已关闭' }}
          </button>
          <span class="text-[12px] text-ink-400">目标未达成时每天最多提醒一次</span>
          <div class="flex items-center gap-2 sm:ml-auto">
            <span class="text-[12px] text-ink-500">学习榜公开</span>
            <button class="tag cursor-pointer" :class="pref.leaderboard_public ? 'bg-brand-600 text-white' : ''" @click="togglePref('leaderboard_public')">
              {{ pref.leaderboard_public ? '公开' : '不公开' }}
            </button>
            <button class="btn-outline px-2 py-0.5 text-[11px]" @click="checkRemind">立即检查提醒</button>
          </div>
        </div>
        <p class="mt-1.5 text-[11px] leading-5 text-ink-400">提醒走站内通知，点「立即检查」可以看看今天还差多少分钟；不公开学习榜则不会出现在「小组 → 学习榜」里。</p>
      </div>

      <!-- F523 每日学习目标与达成率 -->
      <div class="card p-4">
        <div class="flex flex-wrap items-center gap-4">
          <div class="min-w-[220px] flex-1">
            <div class="mb-1 flex items-center justify-between text-[12px]">
              <span class="font-medium text-ink-700">今日目标 {{ goal.target_minutes || 0 }} 分钟</span>
              <span :class="goal.achieved ? 'font-medium text-emerald-600' : 'text-ink-400'">
                {{ goal.achieved ? '✓ 已达成' : '已学 ' + (goal.today_minutes || 0) + ' 分钟 · ' + (goal.rate || 0) + '%' }}
              </span>
            </div>
            <div class="h-2.5 overflow-hidden rounded-pill bg-ink-100">
              <div class="h-full transition-all" :class="goal.achieved ? 'bg-emerald-500' : 'bg-brand-500'" :style="{ width: Math.min(100, goal.rate || 0) + '%' }"></div>
            </div>
          </div>
          <div class="flex items-center gap-1">
            <input v-model.number="goalInput" type="number" min="5" max="1440" step="5" class="input h-8 w-24 text-[12px]" placeholder="目标分钟" />
            <button class="btn-outline px-3 py-1.5" @click="saveGoal">设定目标</button>
          </div>
        </div>
        <!-- 390 本周达成预测 -->
        <div v-if="forecast.message" class="mt-2 flex flex-wrap items-center gap-2 rounded-control bg-ink-50 px-2.5 py-1.5 text-[11px] leading-5">
          <span class="font-medium text-ink-600">达成预测</span>
          <span class="text-ink-500">{{ forecast.message }}</span>
          <span v-if="forecast.week_target" class="ml-auto text-ink-400">
            本周目标 {{ forecast.week_target }} 分钟 · 近 7 天日均 {{ forecast.avg_7d || 0 }} 分钟
            <template v-if="forecast.need_minutes"> · 需补 {{ forecast.need_minutes }} 分钟</template>
          </span>
        </div>
        <div v-else class="mt-2 text-[11px] leading-5 text-ink-400">达成预测暂不可用：设好每日目标并打卡几天后，这里会给出本周达成概率与还需补的时长。</div>
      </div>

      <!-- F522 连续打卡 streak -->
      <div class="card p-4">
        <div class="flex flex-wrap items-center gap-4">
          <div class="text-center">
            <div class="text-[26px] font-bold leading-none text-orange-500">{{ streak.current || 0 }}</div>
            <div class="mt-1 text-[11px] text-ink-400">连续打卡(天)</div>
          </div>
          <div class="h-9 w-px bg-ink-100"></div>
          <div class="grid flex-1 grid-cols-3 gap-3 text-center">
            <div><div class="text-[16px] font-semibold text-ink-800">{{ streak.longest || 0 }}</div><div class="text-[11px] text-ink-400">最长连续</div></div>
            <div><div class="text-[16px] font-semibold text-ink-800">{{ streak.today_minutes || 0 }}</div><div class="text-[11px] text-ink-400">今日分钟</div></div>
            <div><div class="text-[16px] font-semibold text-ink-800">{{ streak.total_minutes || 0 }}</div><div class="text-[11px] text-ink-400">累计分钟</div></div>
          </div>
        </div>
        <div class="mt-3">
          <div class="mb-1 flex justify-between text-[10px] text-ink-400"><span>近 21 天打卡</span><span>今天</span></div>
          <div class="flex gap-1">
            <div v-for="(c,i) in streakCells" :key="i" class="flex-1 rounded-sm"
                 :class="c.on?'bg-orange-400':(c.today?'bg-ink-50 ring-1 ring-orange-300':'bg-ink-50')"
                 style="height:14px" :title="c.date + (c.on?' 已打卡':' 未打卡')"></div>
          </div>
          <p class="mt-2 text-[11px] leading-5 text-ink-400">当天在「专注记录」里有任意一次打卡即算连续；断一天连续天数清零，今天还没记录就去补一次。</p>
        </div>
      </div>

      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">近 14 天趋势</h3>
        <div class="flex items-end gap-1" style="height: 80px">
          <div v-for="(d, i) in trend14" :key="i" class="flex-1 rounded-t bg-brand-400" :style="{ height: Math.max(4, d.minutes / (maxTrend || 1) * 76) + 'px' }" :title="d.date + ' ' + d.minutes + '分钟'"></div>
        </div>
        <div class="mt-1 flex justify-between text-[10px] text-ink-400"><span>14天前</span><span>今天</span></div>
      </div>

      <!-- 389 学习时长 × 工具使用双序列 -->
      <div class="card p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">学习时长 × 工具使用（近 {{ usage.days || usageDays }} 天）</h3>
          <select v-model.number="usageDays" class="input ml-auto h-8 w-24 text-[12px]" @change="loadUsage">
            <option :value="7">7 天</option>
            <option :value="14">14 天</option>
            <option :value="30">30 天</option>
          </select>
        </div>
        <div v-if="usageSeries.length" class="space-y-2">
          <div class="flex items-end gap-1" style="height: 66px">
            <div v-for="d in usageSeries" :key="'m' + d.date" class="flex-1 rounded-t bg-brand-400"
                 :style="{ height: Math.max(3, d.minutes / (usageMax || 1) * 62) + 'px' }" :title="d.date + '：' + d.minutes + ' 分钟'"></div>
          </div>
          <div class="flex items-end gap-1" style="height: 38px">
            <div v-for="d in usageSeries" :key="'c' + d.date" class="flex-1 rounded-t bg-emerald-400"
                 :style="{ height: Math.max(2, d.tool_calls / (usageCallsMax || 1) * 34) + 'px' }" :title="d.date + '：' + d.tool_calls + ' 次工具'"></div>
          </div>
          <div class="flex flex-wrap items-center gap-3 text-[11px] text-ink-400">
            <span class="flex items-center gap-1"><i class="inline-block h-2 w-2 rounded-sm bg-brand-400"></i>学习分钟</span>
            <span class="flex items-center gap-1"><i class="inline-block h-2 w-2 rounded-sm bg-emerald-400"></i>工具使用次数</span>
            <span class="ml-auto">合计 {{ usage.totals?.minutes || 0 }} 分钟 / {{ usage.totals?.tool_calls || 0 }} 次 · 活跃 {{ usage.totals?.active_days || 0 }} 天</span>
          </div>
        </div>
        <div v-else class="text-[12px] leading-6 text-ink-400">
          还没有可对比的数据：去「专注记录」打卡，或使用学习工具（公式计算、单位换算、词典等），这里会叠出按日的两条走势。
        </div>
      </div>

      <!-- F541 弱项雷达：按学科/题型的订正率，右侧给补弱顺序 -->
      <div class="card p-4">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-[14px] font-semibold text-ink-800">弱项雷达（错题订正率）</h3>
          <div class="flex gap-1 text-[11px]">
            <button class="rounded px-2 py-0.5" :class="weakMode==='subject'?'bg-brand-600 text-white':'bg-ink-100 text-ink-500'" @click="weakMode='subject'">按学科</button>
            <button class="rounded px-2 py-0.5" :class="weakMode==='type'?'bg-brand-600 text-white':'bg-ink-100 text-ink-500'" @click="weakMode='type'">按题型</button>
          </div>
        </div>
        <div v-if="weakOrder.length" class="grid gap-3" :class="weakAxes.length>=3?'md:grid-cols-5':''">
          <svg v-if="weakAxes.length>=3" class="w-full md:col-span-3" viewBox="0 0 300 250" role="img" aria-label="弱项雷达图">
            <polygon v-for="(g,i) in weakRings" :key="'g'+i" :points="g.pts" fill="none" stroke="#e5e7eb" :stroke-width="g.v===100?1.3:1" />
            <line v-for="(s,i) in weakSpokes" :key="'s'+i" :x1="s.x1" :y1="s.y1" :x2="s.x2" :y2="s.y2" stroke="#e5e7eb" stroke-width="1" />
            <polygon :points="weakDataPts" fill="rgba(79,70,229,0.16)" stroke="#4f46e5" stroke-width="1.6" />
            <circle v-for="(d,i) in weakDots" :key="'d'+i" :cx="d.x" :cy="d.y" r="2.7" :fill="d.weak?'#dc2626':'#4f46e5'" />
            <text v-for="(l,i) in weakLabels" :key="'l'+i" :x="l.x" :y="l.y" :text-anchor="l.anchor" :fill="l.weak?'#dc2626':'#6b7280'" font-size="10">{{ l.nm }} {{ l.rate }}%</text>
          </svg>
          <div class="self-center space-y-1.5" :class="weakAxes.length>=3?'md:col-span-2':''">
            <div class="text-[12px] font-medium text-ink-600">优先补弱顺序</div>
            <div v-for="(o,i) in weakOrder" :key="i" class="flex items-center gap-2 text-[12px]">
              <span class="w-4 text-ink-400">{{ i+1 }}</span>
              <span :class="o.weak?'font-medium text-red-600':'text-ink-600'">{{ o.name }}</span>
              <span class="ml-auto text-ink-400">{{ Math.round(o.fixed_rate) }}%</span>
            </div>
            <p class="pt-1 text-[11px] leading-5 text-ink-400">红色＝订正率低于 60%，越靠前越该先补；订正率会随错题本「订正掌握」与错题重练上升。</p>
            <p v-if="weakAxes.length<3" class="text-[11px] leading-5 text-ink-400">当前涉及的学科/题型还少，再多积累一些错题，这里会展开完整雷达。</p>
          </div>
        </div>
        <div v-else class="grid h-28 place-items-center px-6 text-center text-[12px] leading-6 text-ink-400">
          还没有足够错题：去「题库」智能组卷交卷或「刷题训练」，把做错的题留下来，这里会按学科、题型算出订正率并画成雷达。
        </div>
      </div>

      <!-- F521 今日复习队列（艾宾浩斯） -->
      <div class="card p-4">
        <h3 class="mb-2 flex items-center gap-2 text-[14px] font-semibold text-ink-800">
          今日复习队列（艾宾浩斯）
          <span v-if="rqCount" class="tag bg-orange-50 text-orange-600">{{ rqCount }} 项待复习</span>
        </h3>
        <template v-if="rqData">
          <div v-if="rqData.words && rqData.words.length" class="mb-2 space-y-1.5">
            <div v-for="w in rqData.words" :key="'w'+w.id" class="flex items-center gap-2 rounded-control bg-ink-50 px-3 py-2 text-[12px]">
              <span class="font-medium text-ink-800">{{ w.word }}</span>
              <span class="text-ink-400">{{ w.phonetic }}</span>
              <span class="text-ink-500">{{ w.meaning }}</span>
              <button class="btn-outline ml-auto px-2 py-0.5" @click="markReview('word',w.id)">已复习</button>
            </div>
          </div>
          <div v-if="rqData.mistakes && rqData.mistakes.length" class="space-y-1.5">
            <div v-for="m in rqData.mistakes" :key="'m'+m.id" class="flex items-center gap-2 rounded-control bg-ink-50 px-3 py-2 text-[12px]">
              <span class="tag">{{ SUBJECT_CN[m.subject] || m.subject }}</span>
              <span class="line-clamp-1 flex-1 text-ink-500">{{ m.stem }}</span>
              <button class="btn-outline px-2 py-0.5" @click="markReview('mistake',m.id)">已复习</button>
            </div>
          </div>
          <div v-if="!rqCount" class="grid h-20 place-items-center text-center text-[12px] leading-6 text-ink-400">
            今天没有到期的复习：生词和错题会按遗忘曲线在该复习时出现在这里；先去积累或专注今天的学习。
          </div>
        </template>
        <div v-else class="h-16 animate-pulse rounded bg-ink-50"></div>
      </div>

      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">学习日历（{{ calYear }}年{{ calMonth + 1 }}月）</h3>
        <div class="mb-1 flex justify-between text-[12px]">
          <button class="btn-outline px-2" @click="shiftMonth(-1)">‹ 上月</button>
          <button class="btn-outline px-2" @click="shiftMonth(1)">下月 ›</button>
        </div>
        <div class="grid grid-cols-7 gap-1 text-center text-[11px] text-ink-400">
          <span v-for="w in ['一','二','三','四','五','六','日']" :key="w">{{ w }}</span>
        </div>
        <div class="mt-1 grid grid-cols-7 gap-1">
          <div v-for="(cell, i) in calendarCells" :key="i"
               class="aspect-square rounded text-[11px] leading-6"
               :class="cell.day ? (cell.minutes ? 'bg-brand-500 text-white' : 'bg-ink-50 text-ink-400') : ''"
               :title="cell.day ? cell.day + '：' + (cell.minutes ? cell.minutes + '分钟' : '无记录') : ''">
            {{ cell.day || '' }}
          </div>
        </div>
      </div>

      <!-- F519 学习报告 + F533 数据备份 -->
      <div class="card p-4">
        <h3 class="mb-3 text-[14px] font-semibold text-ink-800">学习报告与数据管理</h3>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="rounded-control border border-ink-100 p-3">
            <div class="mb-2 flex items-center gap-2">
              <span class="text-[13px] font-medium text-ink-700">月度学习报告</span>
              <input v-model="repMonth" type="month" class="input ml-auto h-8 w-36 text-[12px]" />
            </div>
            <div class="flex gap-2">
              <button class="btn-primary flex-1" @click="genReport">生成报告</button>
              <button class="btn-outline flex-1" :disabled="!report" @click="downloadReport">下载 .md</button>
            </div>
            <pre v-if="report" class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-control bg-ink-50 p-2 font-sans text-[11px] leading-5 text-ink-600">{{ report.markdown }}</pre>
            <p v-else class="mt-2 text-[11px] leading-5 text-ink-400">选月份点「生成报告」：汇总时长、活跃天数、错题订正与进度更新，可直接保存成 Markdown。</p>
          </div>
          <div class="rounded-control border border-ink-100 p-3">
            <div class="mb-2 text-[13px] font-medium text-ink-700">学习数据导出 / 导入</div>
            <button class="btn-primary w-full" @click="exportBackup">导出全部数据（JSON）</button>
            <label class="btn-outline mt-2 block w-full cursor-pointer text-center">
              导入备份（JSON）
              <input type="file" accept=".json,application/json" class="hidden" @change="importBackup" />
            </label>
            <p class="mt-2 text-[11px] leading-5 text-ink-400">导出含进度、收藏、生词、错题、专注、计划；导入只新建、不覆盖现有数据。</p>
          </div>
        </div>
      </div>

      <!-- F540 学习徽章墙 -->
      <div class="card p-4">
        <h3 class="mb-3 flex items-center gap-2 text-[14px] font-semibold text-ink-800">
          学习徽章
          <span class="tag-brand">已解锁 {{ badges.unlocked || 0 }}/{{ badges.total || 0 }}</span>
          <button class="btn-outline ml-auto px-2 py-0.5" @click="loadBadges">检查新徽章</button>
        </h3>
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="b in badges.list" :key="b.code" class="flex items-center gap-3 rounded-control border p-2.5"
               :class="b.unlocked ? 'border-amber-200 bg-amber-50/60' : 'border-ink-100 opacity-60'">
            <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[15px]"
                 :class="b.unlocked ? 'bg-amber-400 text-white' : 'bg-ink-100 text-ink-300'">{{ b.unlocked ? '🏅' : '·' }}</div>
            <div class="min-w-0">
              <div class="text-[13px] font-medium" :class="b.unlocked ? 'text-ink-800' : 'text-ink-400'">{{ b.title }}</div>
              <div class="text-[11px] text-ink-400">{{ b.desc }}</div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 学习进度 + 掌握度 -->
    <template v-else-if="tab === 'progress'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        左边是 upsert 表单：领域选编程/学科/工具，目标标识填 python、junior.math 这类 key，同一组 key 重复保存只会更新不会新建；
        拖滑块定百分比、选状态、写备注。下面按学科算「错题掌握度」。右边列表每条都能点开——看名称、目标、备注、
        更新时间和该进度的变更历史。
      </p>
      <div class="grid grid-cols-12 gap-4">
        <div class="card col-span-12 p-4 lg:col-span-5">
          <h3 class="mb-3 text-[14px] font-semibold text-ink-800">记录 / 更新进度</h3>
          <div class="space-y-2">
            <select v-model="pf.domain" class="input"><option value="programming">编程</option><option value="school">学科</option><option value="tool">工具</option></select>
            <input v-model="pf.target_key" class="input" placeholder="目标标识，如 python 或 junior.math" />
            <input v-model="pf.target_name" class="input" placeholder="目标名称，如 Python / 初中数学" />
            <div class="flex items-center gap-2"><input v-model.number="pf.percent" type="range" min="0" max="100" class="flex-1" /><span class="w-12 text-[13px] text-brand-700">{{ pf.percent }}%</span></div>
            <select v-model="pf.status" class="input"><option value="learning">学习中</option><option value="finished">已完成</option></select>
            <input v-model="pf.note" class="input" placeholder="备注（可选）" />
            <button class="btn-primary w-full" @click="saveProgress">保存进度</button>
          </div>
          <div v-if="mastery.by_subject" class="mt-4">
            <h3 class="mb-2 text-[14px] font-semibold text-ink-800">错题掌握度</h3>
            <div v-for="(v, k) in mastery.by_subject" :key="k" class="mb-1.5">
              <div class="flex justify-between text-[12px] text-ink-500"><span>{{ k }}</span><span>{{ v.mastered }}/{{ v.total }}（{{ v.mastery }}%）</span></div>
              <div class="h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: v.mastery + '%' }"></div></div>
            </div>
          </div>
          <div v-else class="mt-4 rounded-control bg-ink-50 p-3 text-[12px] leading-6 text-ink-400">
            还没有错题掌握度：去「题库与组卷」或「编程刷题训练」把做错的题收进错题本，这里会按学科算出订正率。
          </div>
        </div>
        <div class="card col-span-12 p-4 lg:col-span-7">
          <h3 class="mb-3 text-[14px] font-semibold text-ink-800">进度列表（{{ progress.length }}）· 点一条看详情</h3>
          <div v-for="p in progress" :key="p.id" class="mb-2 rounded-control border p-3 transition-colors"
            :class="openP === p.id ? 'border-brand-300 bg-brand-50/40 ring-2 ring-brand-100' : 'border-ink-100'">
            <button class="flex w-full items-center gap-2 text-left" @click="toggleP(p.id)">
              <span class="tag-brand">{{ domainName(p.domain) }}</span><span class="text-[13px] font-medium text-ink-800">{{ p.target_name || p.target_key }}</span>
              <span v-if="p.status === 'finished'" class="tag bg-emerald-50 text-emerald-600">已完成</span>
              <span class="ml-auto text-[12px] text-brand-600">{{ openP === p.id ? '收起 ▲' : '详情 ▼' }}</span>
            </button>
            <div class="mt-1.5 h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: p.percent + '%' }"></div></div>
            <div class="mt-1 text-[11px] text-ink-400">{{ p.percent }}% · 更新于 {{ formatTime(p.updated_at) }}</div>

            <div v-if="openP === p.id" class="mt-2 space-y-2 border-t border-ink-100 pt-2">
              <div class="grid grid-cols-1 gap-x-4 gap-y-1 text-[12px] text-ink-600 md:grid-cols-2">
                <div><span class="text-ink-400">名称：</span>{{ p.target_name || '（未填写目标名称）' }}</div>
                <div><span class="text-ink-400">目标标识：</span><code class="rounded bg-ink-100 px-1 font-mono text-[11px]">{{ p.target_key }}</code></div>
                <div><span class="text-ink-400">领域：</span>{{ domainName(p.domain) }}</div>
                <div><span class="text-ink-400">状态：</span>{{ p.status === 'finished' ? '已完成' : '学习中' }}</div>
                <div><span class="text-ink-400">备注：</span>{{ p.note || '（无备注）' }}</div>
                <div><span class="text-ink-400">更新时间：</span>{{ formatTime(p.updated_at) }}　<span class="text-ink-400">创建于 {{ formatTime(p.created_at) }}</span></div>
              </div>
              <div class="rounded-control bg-white p-2 text-[12px] leading-6 text-ink-500 ring-1 ring-ink-100">
                <span class="font-semibold text-ink-600">相关说明：</span>{{ progressHint(p) }}
              </div>
              <div>
                <div class="mb-1 text-[12px] font-semibold text-ink-600">变更历史</div>
                <div v-if="histOf(p).length" class="space-y-0.5">
                  <div v-for="(h, hi) in histOf(p)" :key="hi" class="text-[11px] leading-5 text-ink-500">
                    {{ h.at }}：进度更新到 {{ h.percent }}%<span v-if="h.note">（{{ h.note }}）</span>
                  </div>
                </div>
                <div v-else class="rounded-control bg-ink-50 p-2 text-[11px] leading-5 text-ink-400">
                  暂无历史：本次会话里点一次「保存进度」就会在这里记下一条；后端若返回 history 字段也会一并展示。
                </div>
              </div>
              <div>
                <div class="mb-1 text-[12px] font-semibold text-ink-600">相关收藏 / 错题</div>
                <div v-if="relatedMap[p.id] && relatedMap[p.id].length" class="space-y-0.5">
                  <div v-for="(r, ri) in relatedMap[p.id]" :key="ri" class="text-[11px] leading-5 text-ink-500">
                    <span class="tag-brand mr-1">{{ r.kind }}</span>{{ r.title }}
                  </div>
                </div>
                <div v-else class="rounded-control bg-ink-50 p-2 text-[11px] leading-5 text-ink-400">
                  点开时按目标自动汇总相关收藏片段或错题；这里暂无，说明这块还没有关联记录。
                </div>
              </div>
            </div>
          </div>
          <div v-if="!progress.length" class="grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
            还没有任何进度：在左侧选领域、填目标标识（如 python）、拖一下滑块点「保存进度」，这里就会长出第一根进度条。
          </div>
        </div>
      </div>

      <!-- 384 学科 × 周 掌握度热力图 -->
      <div class="card p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">学科 × 周 掌握度热力图（近 {{ heatmap.days || 90 }} 天）</h3>
          <button class="btn-outline ml-auto px-2 py-0.5 text-[11px]" @click="loadHeatmap">刷新</button>
        </div>
        <div v-if="heatmap.subjects && heatmap.subjects.length" class="overflow-x-auto">
          <div class="min-w-[560px]">
            <div class="flex items-center gap-1 text-[10px] text-ink-400">
              <span class="w-16 shrink-0">学科</span>
              <span v-for="w in heatmap.weeks" :key="w.start" class="flex-1 text-center">{{ w.label }}</span>
              <span class="w-10 shrink-0 text-right">订正率</span>
            </div>
            <div v-for="s in heatmap.subjects" :key="s.subject" class="mt-1 flex items-center gap-1">
              <span class="w-16 shrink-0 truncate text-[12px] text-ink-600" :title="s.subject_name">{{ s.subject_name }}</span>
              <div v-for="c in s.cells" :key="c.week" class="h-4 flex-1 rounded-sm" :class="heatCls(c.rate)"
                   :title="c.week + ' 那一周：订正 ' + c.mastered + '/' + c.total + (c.rate === null ? '（无错题）' : '（' + c.rate + '%）')"></div>
              <span class="w-10 shrink-0 text-right text-[11px] text-ink-500">{{ s.rate }}%</span>
            </div>
            <div class="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-ink-400">
              <span>颜色越深订正率越高：</span>
              <span v-for="lg in HEAT_LEGEND" :key="lg.cls" class="flex items-center gap-1">
                <i class="inline-block h-3 w-4 rounded-sm" :class="lg.cls"></i>{{ lg.label }}
              </span>
              <span class="flex items-center gap-1"><i class="inline-block h-3 w-4 rounded-sm bg-ink-100"></i>该周无错题</span>
            </div>
          </div>
        </div>
        <div v-else class="text-[12px] leading-6 text-ink-400">
          还没有可成图的错题：去「题库」做题并「收进错题本」，或在这里用「错题本」批量导入；之后每个学科每周的订正率会画成一行色块，断档一眼可见。
        </div>
      </div>

      <!-- 376 薄弱错因聚类（前 5） -->
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">薄弱错因聚类（前 5）</h3>
        <div v-if="clusters.length" class="space-y-1.5">
          <div v-for="c in clusters" :key="c.subject + c.cause" class="flex flex-wrap items-center gap-2 rounded-control bg-ink-50 px-2.5 py-1.5 text-[12px]">
            <span class="w-4 text-ink-400">{{ c.rank }}</span>
            <span class="tag">{{ c.subject_name }}</span>
            <span class="text-[13px] font-medium text-ink-800">{{ c.cause_name }}</span>
            <span class="text-ink-400">{{ c.total }} 题 · 订正 {{ c.mastered }} 题（{{ c.rate }}%）</span>
            <span class="ml-auto text-[11px] text-rose-500">薄弱度 {{ c.weakness }}</span>
          </div>
          <p class="pt-1 text-[11px] leading-5 text-ink-400">薄弱度＝题量 × 未订正比例，越靠前越该先补；到「错题本」按同科筛出这些题集中订正，聚类会随订正率下降。</p>
        </div>
        <div v-else class="text-[12px] leading-6 text-ink-400">
          还没有错因数据：在「题库 · 错题本」给每道题选一个「错因归类」（粗心 / 概念不清 / 方法不会…），这里会聚合出最该先补的 5 组。
        </div>
      </div>
    </template>

    <!-- 代码收藏 -->
    <template v-else-if="tab === 'bookmark'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        自己的代码剪贴板：上面一行填语言 key（python / go…）、标题和代码点「收藏」即可新增；
        下面两列黑底展示，编程广场右上角「收藏片段/语言」进来的学习卡也汇到这里。用不上的直接删，云端保存换设备不丢。
      </p>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="bf.language" class="input col-span-2" placeholder="语言 key，如 python" />
          <input v-model="bf.title" class="input col-span-3" placeholder="标题" />
          <input v-model="bf.code" class="input col-span-6" placeholder="代码 / 命令" />
          <button class="btn-primary col-span-1" @click="addBookmark">收藏</button>
        </div>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <div v-for="b in bookmarks" :key="b.id" class="card p-3">
          <div class="flex items-center gap-2"><span class="tag-brand">{{ b.language }}</span><span class="text-[13px] font-semibold text-ink-800">{{ b.title }}</span>
            <button class="btn-danger ml-auto" @click="delBookmark(b.id)">删除</button></div>
          <pre class="mt-1.5 overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ b.code }}</pre>
          <div v-if="b.note" class="mt-1 text-[12px] text-ink-400">{{ b.note }}</div>
        </div>
        <div v-if="!bookmarks.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          收藏夹还是空的：去「编程语言广场」选一门语言点「收藏片段/语言」，或直接在上面贴一段常用命令。
        </div>
      </div>
    </template>

    <!-- 专注记录 -->
    <template v-else-if="tab === 'session'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        打卡式记录：学完一次就填科目、分钟、日期点「打卡」（番茄钟建议一次 25 分钟）。上面三张卡统计累计分钟、
        次数和小时，中间按科目汇总出“哪科花得最多”，下面逐条列出可删除——「学习概览」的柱状图与月历读的就是这些数据。
      </p>
      <div class="grid grid-cols-3 gap-3">
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ sessSummary.total_minutes || 0 }}</div><div class="text-[12px] text-ink-400">累计分钟</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ sessSummary.count || 0 }}</div><div class="text-[12px] text-ink-400">专注次数</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ Math.round((sessSummary.total_minutes || 0) / 60 * 10) / 10 }}</div><div class="text-[12px] text-ink-400">累计小时</div></div>
      </div>

      <!-- F524 番茄钟专注闭环 -->
      <div class="card p-4">
        <h3 class="mb-3 flex flex-wrap items-center gap-2 text-[14px] font-semibold text-ink-800">
          番茄钟 · {{ pomoState.mode === 'work' ? (pomoState.running ? '专注中' : '待开始') : '休息中' }}
          <span class="tag-brand">今日 {{ pomoStat.total_rounds || 0 }} 轮 · 完整 {{ pomoStat.finished || 0 }} · 打断 {{ pomoStat.interrupted || 0 }} · {{ pomoStat.focus_minutes || 0 }} 分钟</span>
        </h3>
        <div class="flex flex-wrap items-center gap-5">
          <div class="grid h-28 w-28 shrink-0 place-items-center rounded-full text-[26px] font-bold tabular-nums"
               :class="pomoState.mode === 'work' ? 'bg-brand-50 text-brand-700 ring-8 ring-brand-100' : 'bg-emerald-50 text-emerald-600 ring-8 ring-emerald-100'">
            {{ pomoClock }}
          </div>
          <div class="min-w-[240px] flex-1 space-y-2">
            <div class="flex flex-wrap gap-2">
              <button class="btn-primary px-4" @click="togglePomo">{{ pomoState.running ? '暂停' : '开始' }}</button>
              <button class="btn-outline px-3" @click="resetPomo">重置</button>
              <button class="btn-outline px-3" :class="pomoState.marked ? 'text-rose-500' : ''" @click="markPomoInterrupt">{{ pomoState.marked ? '已记打断' : '标记打断' }}</button>
              <button class="btn-outline px-3" @click="finishPomoNow">结束并记录</button>
            </div>
            <p class="text-[11px] leading-5 text-ink-400">
              专注 {{ pomoState.workMin }} 分钟、休息 {{ pomoState.breakMin }} 分钟为一轮：专注倒计时走完自动记一轮并进入休息；中途被打断点「标记打断」，该轮按打断记录；「结束并记录」按实际专注分钟记。轮次同步进打卡记录。
            </p>
          </div>
        </div>
      </div>

      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="sf.subject" class="input col-span-3" placeholder="科目/主题，如 数学" />
          <input v-model.number="sf.minutes" type="number" class="input col-span-2" placeholder="分钟" />
          <input v-model="sf.study_date" type="date" class="input col-span-3" />
          <button class="btn-primary col-span-2" @click="addSession">打卡</button>
          <div class="col-span-2 text-[12px] leading-8 text-ink-400">番茄钟建议 25 分钟</div>
        </div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">按科目统计</h3>
        <div class="flex flex-wrap gap-2"><span v-for="(m, k) in sessSummary.by_subject" :key="k" class="tag-brand">{{ k }}：{{ m }} 分钟</span></div>
        <div v-if="!Object.keys(sessSummary.by_subject || {}).length" class="text-[13px] leading-6 text-ink-400">
          还没有按科目汇总：在上面填「数学 · 25 分钟」打卡一次，这里就会出现「数学：25 分钟」的标签。
        </div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">打卡记录</h3>
        <div v-for="s in sessions" :key="s.id" class="flex items-center gap-3 border-b border-ink-50 py-1.5 text-[13px]">
          <span class="tag-brand">{{ s.subject }}</span><span>{{ s.minutes }} 分钟</span><span class="text-ink-400">{{ s.study_date }}</span>
          <button class="btn-danger ml-auto" @click="delSession(s.id)">删除</button>
        </div>
        <div v-if="!sessions.length" class="text-[13px] leading-6 text-ink-400">
          今天还没打卡：填科目和分钟点「打卡」，学习日历和 14 天趋势立刻亮起来。
        </div>
      </div>
    </template>

    <!-- 学习计划 -->
    <template v-else-if="tab==='plan'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        把大目标拆到每一天：填计划名称（如「30 天背单词」）、科目、总任务量、天数和开始日期点「生成计划」，
        系统按天排出任务（默认每 4 天休一天）。卡片上进度条用 − / ＋ 手动推进完成量，点「查看每日安排」
        展开逐日清单，不需要的计划直接删。
      </p>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="plf.title" class="input col-span-3" placeholder="计划名称，如 30 天背单词" />
          <input v-model="plf.subject" class="input col-span-2" placeholder="科目" />
          <input v-model.number="plf.total" type="number" class="input col-span-2" placeholder="总任务量" />
          <input v-model.number="plf.days" type="number" class="input col-span-1" placeholder="天数" />
          <input v-model="plf.start_date" type="date" class="input col-span-2" />
          <button class="btn-primary col-span-2" @click="addPlan">生成计划</button>
        </div>
      </div>
      <div class="grid gap-3 md:grid-cols-2">
        <div v-for="p in plans" :key="p.id" class="card p-4">
          <div class="flex items-center gap-2"><span class="text-[14px] font-semibold text-ink-800">{{ p.title }}</span><span class="tag">{{ p.subject }}</span>
            <button class="btn-danger ml-auto" @click="delPlan(p.id)">删除</button></div>
          <div class="mt-2 h-2 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: (p.total ? p.finished / p.total * 100 : 0) + '%' }"></div></div>
          <div class="mt-1 flex items-center gap-2 text-[12px] text-ink-500">
            <span>已完成 {{ p.finished }}/{{ p.total }}，{{ p.days }} 天</span>
            <button class="btn-outline px-2 py-0.5" @click="bumpPlan(p, -1)">-</button>
            <button class="btn-outline px-2 py-0.5" @click="bumpPlan(p, 1)">+</button>
          </div>
          <!-- 383 每日排程 -->
          <div class="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <input v-model.number="schedMinutes[p.id]" type="number" min="5" max="600" step="5" class="input h-8 w-24 text-[12px]" placeholder="每日分钟" />
            <button class="btn-outline px-2 py-0.5" :disabled="schedLoading[p.id]" @click="genSchedule(p)">{{ schedLoading[p.id] ? '排程中…' : '生成今日任务' }}</button>
            <span v-if="schedules[p.id]" class="text-ink-400">共 {{ schedules[p.id].schedule.length }} 天 · 截止 {{ schedules[p.id].deadline }}</span>
          </div>
          <div v-if="schedules[p.id]" class="mt-2 rounded-control bg-ink-50 p-2 text-[11px] leading-5 text-ink-600">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-ink-700">今日任务：</span>
              <template v-if="todayTask(p)">
                <span>{{ todayTask(p).tasks }} 项 · 约 {{ todayTask(p).minutes }} 分钟</span>
                <button class="btn-primary ml-auto px-2 py-0.5 text-[11px]" :disabled="writingSched[p.id]" @click="writeScheduleSession(p)">
                  {{ writingSched[p.id] ? '写入中…' : '一键写入打卡' }}
                </button>
              </template>
              <span v-else class="text-ink-400">今天不在排程范围内（计划已结束或尚未开始）</span>
            </div>
            <div class="mt-1 flex flex-wrap gap-1">
              <span v-for="d in schedules[p.id].schedule.slice(0, 7)" :key="d.date" class="tag" :class="d.is_today ? 'bg-brand-600 text-white' : ''">
                {{ d.date.slice(5) }} 周{{ d.weekday }} · {{ d.tasks }} 项
              </span>
            </div>
            <div class="mt-1 text-ink-400">剩余 {{ schedules[p.id].remaining }} 项{{ schedules[p.id].truncated ? '（排程超 90 天已截断展示）' : '' }}</div>
          </div>
          <details class="mt-2" @toggle="onPlanToggle(p)"><summary class="cursor-pointer text-[12px] text-brand-600">查看每日安排 / 排程说明</summary>
            <div v-if="planExplain[p.id]" class="mt-2 rounded-control bg-ink-50 p-2 text-[11px] leading-5 text-ink-600">
              <div class="font-medium text-ink-700">排程逻辑</div>
              <div>{{ planExplain[p.id].rule }}</div>
              <div class="mt-1 text-ink-400">平均每天约 {{ planExplain[p.id].per_day_avg }} 项；还剩 {{ planExplain[p.id].remain }} 项，当前完成 {{ planExplain[p.id].progress_rate }}%。</div>
            </div>
            <ol class="mt-1 ml-4 list-decimal text-[12px] text-ink-500"><li v-for="(d, i) in p.plan" :key="i">{{ d }}</li></ol>
          </details>
        </div>
        <div v-if="!plans.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          还没有计划：在上面填「100 道题 · 7 天」这类数字点「生成计划」，马上得到一张带每日任务的进度卡。
        </div>
      </div>
    </template>

    <!-- F520 错题重练 -->
    <template v-else-if="tab === 'redrill'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        把错题本里未掌握的题再做一遍：判断题点「正确/错误」，填空题直接写，单选题填选项序号（0=A、1=B…）。
        提交即判分并记录二次正确率；答对可点「标记掌握」移出重练，答错会显示参考答案与解析。
      </p>
      <div class="card flex flex-wrap items-center gap-3 p-3 text-[12px] text-ink-500">
        <span>待重练 <b class="text-brand-700">{{ redrillList.length }}</b> 题</span>
        <span>本轮已答 <b class="text-brand-700">{{ redrillAnswered }}</b> 题、答对 <b class="text-emerald-600">{{ redrillCorrectCount }}</b></span>
        <button class="btn-outline ml-auto px-3 py-1" @click="loadReDrill">刷新 / 换一批</button>
      </div>
      <div v-for="m in redrillList" :key="m.id" class="card p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <span class="tag">{{ SUBJECT_CN[m.subject] || m.subject }}</span>
          <span class="tag-brand">{{ typeName(m.question_type) }}</span>
          <span class="tag">难度{{ m.difficulty }}</span>
          <span v-if="resultOf(m.id)?.correct" class="tag bg-emerald-50 text-emerald-600">本轮答对</span>
        </div>
        <div class="text-[13px] leading-7 text-ink-800">{{ m.stem }}</div>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <template v-if="m.question_type==='judge'">
            <button class="btn-outline px-3 py-1" @click="submitReDrill(m, true)">正确</button>
            <button class="btn-outline px-3 py-1" @click="submitReDrill(m, false)">错误</button>
          </template>
          <template v-else>
            <input v-model="ansMap[m.id]" class="input w-64"
                   :placeholder="m.question_type==='single'?'填选项序号 0=A、1=B、2=C、3=D':'填写答案，多空用英文逗号'"
                   @keyup.enter="submitReDrill(m, ansMap[m.id])" />
            <button class="btn-primary px-3 py-1" @click="submitReDrill(m, ansMap[m.id])">提交</button>
          </template>
          <button v-if="resultOf(m.id)?.correct" class="btn-outline px-3 py-1 text-emerald-600" @click="masterReDrill(m)">标记掌握</button>
        </div>
        <div v-if="resultOf(m.id)" class="mt-2 rounded-control p-2 text-[12px] leading-6"
             :class="resultOf(m.id).correct?'bg-emerald-50 text-emerald-700':'bg-rose-50 text-rose-700'">
          <div>{{ resultOf(m.id).correct ? '✓ 回答正确' : '✗ 回答不正确' }}　参考答案：{{ resultOf(m.id).right_answer }}</div>
          <div v-if="resultOf(m.id).analysis" class="text-ink-600">解析：{{ resultOf(m.id).analysis }}</div>
          <div class="text-ink-400">该题重练 {{ resultOf(m.id).attempts }} 次，重练正确率 {{ resultOf(m.id).redrill_rate }}%</div>
        </div>
      </div>
      <div v-if="!redrillList.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
        暂未掌握的错题是空的：先去「题库 · 智能组卷」或「刷题训练」，把做错的题收进错题本，这里就能重练。
      </div>
    </template>

    <!-- 373/374/375/387/388 错题整理 -->
    <template v-else-if="tab === 'mistake'">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        错题集中整理：CSV / JSON 批量导入（表头写「题干、正确答案、学科、题型、错因」等即可），也能导出成表格或 Anki 记忆卡；
        每道题可以找「相似错题」横向巩固、存为笔记、按复习日期加入待办。订正完点「订正掌握」，热力图与聚类会随之变好。
      </p>
      <div class="card p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">批量导入</h3>
          <select v-model="impFmt" class="input h-8 w-24 text-[12px]">
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
          <button class="btn-primary px-3 py-1" :disabled="importing" @click="doImport">{{ importing ? '导入中…' : '导入' }}</button>
          <span class="text-[11px] text-ink-400">CSV 需带表头；JSON 为对象数组或 {{ '{items: [...]}' }}</span>
        </div>
        <textarea v-model="impText" rows="4" class="input w-full font-mono text-[11px]"
          :placeholder="impFmt === 'csv' ? '题干,正确答案,学科,题型,错因\n三角形内角和是多少?,180,数学,填空题,概念不清' : '[{&quot;stem&quot;:&quot;三角形内角和是多少?&quot;,&quot;answer&quot;:&quot;180&quot;,&quot;subject&quot;:&quot;数学&quot;,&quot;question_type&quot;:&quot;fill&quot;}]'"></textarea>
        <div v-if="impResult" class="mt-2 rounded-control bg-ink-50 p-2 text-[12px] leading-6 text-ink-600">
          <div>共 {{ impResult.total }} 行：新建 <b class="text-emerald-600">{{ impResult.created }}</b>、跳过 {{ impResult.skipped }}（重复 {{ impResult.duplicated || 0 }}、非法 {{ impResult.invalid || 0 }}）</div>
          <div v-for="e in impResult.errors" :key="e.row" class="text-[11px] text-rose-500">第 {{ e.row }} 行：{{ e.error }}</div>
          <div v-if="impResult.errors_truncated" class="text-[11px] text-ink-400">错误过多，仅展示前 20 条</div>
        </div>
        <div v-else class="mt-2 text-[11px] leading-5 text-ink-400">粘贴后点「导入」：按题干去重，非法行会在下面逐行报错，不影响其余行入库。</div>
      </div>

      <div class="card flex flex-wrap items-center gap-2 p-4">
        <h3 class="text-[14px] font-semibold text-ink-800">错题清单</h3>
        <span class="text-[12px] text-ink-400">共 {{ mistakeAll.length }} 道 · 未掌握 {{ mistakeUnmastered }} 道</span>
        <button class="btn-outline px-2 py-0.5" @click="onlyMistakeUnmastered = !onlyMistakeUnmastered">{{ onlyMistakeUnmastered ? '显示全部' : '只看未掌握' }}</button>
        <label class="flex items-center gap-1 text-[12px] text-ink-500 sm:ml-auto">待办截止
          <input v-model="todoDue" type="date" class="input h-8 w-36 text-[12px]" />
        </label>
        <button class="btn-outline px-2 py-0.5" @click="downloadMistakes('csv')">导出 CSV</button>
        <button class="btn-outline px-2 py-0.5" @click="downloadMistakes('anki')">导出 Anki</button>
        <button class="btn-outline px-2 py-0.5" @click="loadMistakeAll">刷新</button>
      </div>

      <div v-for="m in mistakeShown" :key="m.id" class="card p-4" :class="m.mastered ? 'opacity-60' : ''">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag-brand">{{ SUBJECT_CN[m.subject] || m.subject }}</span>
          <span class="tag">{{ typeName(m.question_type) }}</span>
          <span class="tag">难度 {{ m.difficulty }}</span>
          <span v-if="m.cause" class="tag">{{ MISTAKE_CAUSE[m.cause] || m.cause }}</span>
          <span v-if="m.mastered" class="tag bg-emerald-50 text-emerald-600">已订正</span>
        </div>
        <p class="mt-2 text-[13px] leading-6 text-ink-800">{{ m.stem }}</p>
        <div class="mt-1 text-[12px] text-ink-500">正确答案：{{ m.answer || '—' }}　我的答案：{{ m.user_answer || '—' }}</div>
        <div v-if="m.analysis" class="text-[12px] text-ink-400">解析：{{ m.analysis }}</div>
        <div class="mt-2 flex flex-wrap gap-2">
          <button class="btn-outline px-2 py-1 text-[12px]" @click="loadSimilar(m.id)">{{ similarOf === m.id ? '收起相似题' : '相似错题' }}</button>
          <button class="btn-outline px-2 py-1 text-[12px]" @click="toNote(m.id)">存为笔记</button>
          <button class="btn-outline px-2 py-1 text-[12px]" @click="toTodo(m.id)">加入待办</button>
          <button class="btn-outline px-2 py-1 text-[12px]" @click="toggleMistakeMastered(m.id)">{{ m.mastered ? '标为未掌握' : '订正掌握' }}</button>
          <button class="btn-danger ml-auto px-2 py-1 text-[12px]" @click="removeMistakeRow(m.id)">删除</button>
        </div>
        <div v-if="similarOf === m.id" class="mt-2 rounded-control bg-ink-50 p-2 text-[12px] leading-6">
          <div v-if="similarLoading" class="text-ink-400">正在按题干重合度找同科相似题…</div>
          <template v-else-if="similarList.length">
            <div class="mb-1 text-[12px] font-medium text-ink-600">找到 {{ similarList.length }} 道同科相似题</div>
            <div v-for="s in similarList" :key="s.id" class="border-t border-ink-200/60 py-1 first:border-0">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="tag">{{ s.type_name }}</span>
                <span class="tag">{{ s.cause_name }}</span>
                <span v-if="s.mastered" class="tag bg-emerald-50 text-emerald-600">已订正</span>
              </div>
              <div class="mt-0.5 text-ink-700">{{ s.stem }}</div>
              <div class="text-[11px] text-ink-400">
                重合度 {{ Math.round((s.score || 0) * 100) }}%
                <template v-if="s.matched_terms && s.matched_terms.length"> · 共同关键词 {{ s.matched_terms.join(' / ') }}</template>
              </div>
            </div>
          </template>
          <div v-else class="text-ink-400">还没找到相似题：同科且题干用词接近的错题至少要有 2 道；再多攒几道或换一道题试试。</div>
        </div>
      </div>
      <div v-if="!mistakeShown.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
        {{ onlyMistakeUnmastered && mistakeAll.length
          ? '未掌握的错题都订正完了——点「显示全部」可以回看已掌握的题目。'
          : '错题本还是空的：在上面用 CSV / JSON 批量导入，或去「题库 · 题库浏览」把做错的题收进错题本。' }}
      </div>
    </template>

    <!-- 379 学习小组 + 380 学习榜 -->
    <template v-else>
      <StudyGroupPanel />
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import { saveBlob } from '../../utils/download'
import StudyGroupPanel from './StudyGroupPanel.vue'

const app = useAppStore()
const router = useRouter()
const tabs = [
  { v: 'overview', label: '学习概览' },
  { v: 'progress', label: '学习进度' }, { v: 'bookmark', label: '代码收藏' },
  { v: 'session', label: '专注记录' }, { v: 'plan', label: '学习计划' },
  { v: 'redrill', label: '错题重练' }, { v: 'mistake', label: '错题本' },
  { v: 'group', label: '小组' },
]
const tab = ref('overview')
const today = new Date().toISOString().slice(0, 10)
const domainName = (d) => ({ programming: '编程', school: '学科', tool: '工具' })[d] || d
// #192 tab 语义：左右方向键 / Home / End 在标签间切换焦点并激活
function onTabKey(e, i) {
  const n = tabs.length
  let next = -1
  if (e.key === 'ArrowRight') next = (i + 1) % n
  else if (e.key === 'ArrowLeft') next = (i - 1 + n) % n
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = n - 1
  if (next < 0) return
  e.preventDefault()
  switchTab(tabs[next].v)
  e.currentTarget?.parentElement?.querySelectorAll('[role="tab"]')[next]?.focus()
}

const progress = ref([])
const mastery = ref({})
const pf = reactive({ domain: 'programming', target_key: '', target_name: '', percent: 0, status: 'learning', note: '' })
// F544：进度条目可点开 —— 展开区展示名称/目标/备注/更新时间/相关说明与变更历史 + 后端 related
const openP = ref(null)
const histMap = ref({})
const relatedMap = reactive({})
async function toggleP(id) {
  openP.value = openP.value === id ? null : id
  if (openP.value === id && !relatedMap[id]) {
    try { const d = await learnApi.progressDetail(id); relatedMap[id] = d.related || [] } catch { relatedMap[id] = [] }
  }
}
function histOf(p) {
  const api = Array.isArray(p.history)
    ? p.history.map((h) => ({ at: formatTime(h.updated_at || h.created_at || h.at || ''), percent: h.percent, note: h.note || h.message || '' }))
    : []
  const local = histMap.value[`${p.domain}:${p.target_key}`] || []
  return [...api, ...local]
}
function progressHint(p) {
  if (p.status === 'finished') {
    return `已标记「已完成」：${p.target_name || p.target_key} 停在 ${p.percent}%。若又练了新内容，可在左侧用同一目标标识再保存一次，历史会继续往下记。`
  }
  if (!p.percent) {
    return `这条刚建立、进度还是 0%：到左侧把领域和目标标识填成同一组，拖动滑块到 20%~30% 再保存，就能看到第一段推进。`
  }
  return `还差 ${100 - p.percent}% 达成目标：${domainName(p.domain)}领域的「${p.target_name || p.target_key}」按 upsert 更新——同一目标标识重复保存只覆盖百分比与备注，不会产生第二条；下方「错题掌握度」会随你订正错题同步上升。`
}
async function loadProgress() {
  progress.value = (await learnApi.progress()).list
  mastery.value = (await learnApi.mastery())
}
async function saveProgress() {
  if (!pf.target_key) return app.toastMsg('请填写目标标识', 'warn')
  const saved = await learnApi.saveProgress({ ...pf })
  const key = `${pf.domain}:${pf.target_key}`
  const list = histMap.value[key] || (histMap.value[key] = [])
  list.unshift({ at: formatTime(saved?.updated_at || new Date()), percent: saved?.percent ?? pf.percent, note: pf.note || '保存进度' })
  app.toastMsg('进度已保存', 'success')
  await loadProgress()
}

const bookmarks = ref([])
const bf = reactive({ language: 'python', title: '', code: '' })
async function loadBookmarks() { bookmarks.value = (await learnApi.bookmarks()).list }
async function addBookmark() {
  if (!bf.title) return app.toastMsg('请填写标题', 'warn')
  await learnApi.addBookmark({ ...bf }); bf.title = ''; bf.code = ''
  await loadBookmarks()
}
async function delBookmark(id) { await learnApi.delBookmark(id); await loadBookmarks() }

const sessions = ref([])
const sessSummary = ref({})
const sf = reactive({ subject: '数学', minutes: 25, study_date: today })
async function loadSessions() { const data = await learnApi.sessions(); sessions.value = data.list; sessSummary.value = data }
async function addSession() { await learnApi.addSession({ ...sf }); await loadSessions() }
async function delSession(id) { await learnApi.delSession(id); await loadSessions() }

const plans = ref([])
const plf = reactive({ title: '', subject: '', total: 100, days: 7, start_date: today })
async function loadPlans() { plans.value = (await learnApi.plans()).list }
async function addPlan() {
  if (!plf.title) return app.toastMsg('请填写计划名称', 'warn')
  await learnApi.addPlan({ ...plf })
  plf.title = ''
  await loadPlans()
}
async function bumpPlan(p, delta) { await learnApi.updatePlan({ id: p.id, finished: Math.max(0, p.finished + delta) }); await loadPlans() }
async function delPlan(id) { await learnApi.delPlan(id); await loadPlans() }

// ===== 383 学习计划每日排程 =====
const schedules = reactive({})
const schedMinutes = reactive({})
const schedLoading = reactive({})
const writingSched = reactive({})
async function genSchedule(p) {
  const minutes = Number(schedMinutes[p.id]) || 60
  schedLoading[p.id] = true
  try {
    schedules[p.id] = await learnApi.planSchedule(p.id, minutes)
    if (!(schedules[p.id].schedule || []).length) app.toastMsg('该计划已没有剩余任务', 'warn')
  } catch (e) {
    schedules[p.id] = null
    app.toastMsg('排程失败：' + (e?.message || '网络异常'), 'error')
  } finally {
    schedLoading[p.id] = false
  }
}
function todayTask(p) {
  const s = schedules[p.id]
  return s ? (s.schedule || []).find((d) => d.is_today) || null : null
}
async function writeScheduleSession(p) {
  const t = todayTask(p)
  if (!t || !t.minutes) return app.toastMsg('今天没有可写入的任务', 'warn')
  writingSched[p.id] = true
  try {
    await learnApi.addSession({ subject: p.subject || p.title, minutes: t.minutes, study_date: today })
    app.toastMsg(`已写入打卡：${t.minutes} 分钟`, 'success')
    await loadSessions()
    await loadOverview()
  } catch (e) {
    app.toastMsg('写入打卡失败：' + (e?.message || '网络异常'), 'error')
  } finally {
    writingSched[p.id] = false
  }
}

// ===== 378 考试倒计时 =====
const exams = ref({ list: [] })
const exf = reactive({ title: '', exam_date: '', subject: '', target_count: 0 })
async function loadExams() {
  try {
    exams.value = await learnApi.exams()
  } catch (e) {
    exams.value = { list: [] }
    app.toastMsg('考试倒计时加载失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function addExam() {
  if (!exf.title.trim()) return app.toastMsg('请填写考试名称', 'warn')
  if (!exf.exam_date) return app.toastMsg('请选择考试日期', 'warn')
  try {
    await learnApi.saveExam({ ...exf })
    exf.title = ''; exf.exam_date = ''; exf.subject = ''; exf.target_count = 0
    app.toastMsg('考试已添加', 'success')
    await loadExams()
  } catch (e) {
    app.toastMsg('添加失败：' + (e?.message || '日期或题量不合法'), 'error')
  }
}
async function delExam(id) {
  try {
    await learnApi.delExam(id)
    app.toastMsg('已删除该考试', 'success')
    await loadExams()
  } catch (e) {
    app.toastMsg('删除失败：' + (e?.message || '网络异常'), 'error')
  }
}

// ===== 377 学习偏好（每日提醒 / 学习榜公开）=====
const pref = ref({ daily_remind: false, leaderboard_public: false })
const PREF_LABEL = { daily_remind: '每日提醒', leaderboard_public: '学习榜公开' }
async function loadPref() {
  try {
    pref.value = await learnApi.studyPref()
  } catch {
    pref.value = { daily_remind: false, leaderboard_public: false }
  }
}
async function togglePref(key) {
  const next = !pref.value[key]
  try {
    pref.value = await learnApi.saveStudyPref({ [key]: next })
    app.toastMsg(`${PREF_LABEL[key]}已${next ? '开启' : '关闭'}`, 'success')
  } catch (e) {
    app.toastMsg('设置失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function checkRemind() {
  try {
    const r = await learnApi.remindCheck()
    if (r.sent) app.toastMsg(`已发出提醒：今日还差 ${r.gap} 分钟`, 'success')
    else app.toastMsg(r.reason || '当前不需要提醒', 'info')
  } catch (e) {
    app.toastMsg('检查提醒失败：' + (e?.message || '网络异常'), 'error')
  }
}

// ===== 390 每日目标达成预测 =====
const forecast = ref({})
async function loadForecast() {
  try {
    forecast.value = await learnApi.goalForecast()
  } catch {
    forecast.value = {}
  }
}

// ===== 389 学习时长 × 工具使用 =====
const usageDays = ref(30)
const usage = ref({})
const usageSeries = computed(() => usage.value.series || [])
const usageMax = computed(() => Math.max(...usageSeries.value.map((d) => d.minutes), 1))
const usageCallsMax = computed(() => Math.max(...usageSeries.value.map((d) => d.tool_calls), 1))
async function loadUsage() {
  try {
    usage.value = await learnApi.usageReport(usageDays.value)
  } catch (e) {
    usage.value = {}
    app.toastMsg('报表加载失败：' + (e?.message || '网络异常'), 'error')
  }
}

// ===== 384 掌握度热力图 =====
const heatmap = ref({})
const HEAT_LEGEND = [
  { cls: 'bg-rose-200', label: '0–39%' },
  { cls: 'bg-amber-200', label: '40–69%' },
  { cls: 'bg-emerald-300', label: '70–89%' },
  { cls: 'bg-emerald-500', label: '90–100%' },
]
function heatCls(rate) {
  if (rate === null || rate === undefined) return 'bg-ink-100'
  if (rate < 40) return 'bg-rose-200'
  if (rate < 70) return 'bg-amber-200'
  if (rate < 90) return 'bg-emerald-300'
  return 'bg-emerald-500'
}
async function loadHeatmap() {
  try {
    heatmap.value = await learnApi.masteryHeatmap(90)
  } catch (e) {
    heatmap.value = {}
    app.toastMsg('热力图加载失败：' + (e?.message || '网络异常'), 'error')
  }
}

// ===== 376 薄弱错因聚类 =====
const clusterData = ref({ top: [] })
const clusters = computed(() => (clusterData.value.top || []).map((c, i) => ({ ...c, rank: i + 1 })))
async function loadClusters() {
  try {
    clusterData.value = await learnApi.mistakeClusters()
  } catch {
    clusterData.value = { top: [] }
  }
}

// ===== 373/374/375/387/388 错题整理 =====
const impFmt = ref('csv')
const impText = ref('')
const importing = ref(false)
const impResult = ref(null)
const mistakeAll = ref([])
const onlyMistakeUnmastered = ref(false)
const todoDue = ref('')
const MISTAKE_CAUSE = { careless: '粗心失误', concept: '概念不清', review: '审题失误', method: '方法不会', memory: '记忆错误' }
const mistakeUnmastered = computed(() => mistakeAll.value.filter((m) => !m.mastered).length)
const mistakeShown = computed(() => (onlyMistakeUnmastered.value ? mistakeAll.value.filter((m) => !m.mastered) : mistakeAll.value))
async function loadMistakeAll() {
  try {
    const d = await learnApi.mistakes()
    mistakeAll.value = d.list || []
  } catch (e) {
    mistakeAll.value = []
    app.toastMsg('错题本加载失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function doImport() {
  if (!impText.value.trim()) return app.toastMsg('请先粘贴要导入的内容', 'warn')
  importing.value = true
  try {
    impResult.value = await learnApi.importMistakes({ format: impFmt.value, text: impText.value })
    app.toastMsg(`导入完成：新建 ${impResult.value.created} 道，跳过 ${impResult.value.skipped} 行`, 'success')
    await loadMistakeAll()
  } catch (e) {
    impResult.value = null
    app.toastMsg('导入失败：' + (e?.message || '格式或行内容有误'), 'error')
  } finally {
    importing.value = false
  }
}
async function downloadMistakes(fmt) {
  try {
    const blob = await learnApi.exportMistakes(fmt)
    saveBlob(blob, `mistakes_${today}.${fmt === 'anki' ? 'txt' : 'csv'}`)
    app.toastMsg(fmt === 'anki' ? 'Anki 卡包已导出' : 'CSV 已导出', 'success')
  } catch (e) {
    app.toastMsg('导出失败：' + (e?.message || '网络异常'), 'error')
  }
}
const similarOf = ref(null)
const similarLoading = ref(false)
const similarList = ref([])
async function loadSimilar(id) {
  if (similarOf.value === id) { similarOf.value = null; return }
  similarOf.value = id
  similarLoading.value = true
  similarList.value = []
  try {
    const d = await learnApi.similarMistakes(id, 10)
    similarList.value = d.list || []
  } catch (e) {
    similarList.value = []
    app.toastMsg('相似错题加载失败：' + (e?.message || '网络异常'), 'error')
  } finally {
    similarLoading.value = false
  }
}
async function toNote(id) {
  try {
    const r = await learnApi.mistakeToNote(id)
    app.toastMsg('已存为笔记，正在打开…', 'success')
    router.push({ path: '/notes', query: { id: r?.note_id } })
  } catch (e) {
    app.toastMsg('存笔记失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function toTodo(id) {
  try {
    const r = await learnApi.mistakeToTodo(id, todoDue.value || '')
    app.toastMsg(`已加入待办${r?.due_date ? '（' + r.due_date + ' 到期）' : ''}`, 'success')
  } catch (e) {
    app.toastMsg('加入待办失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function toggleMistakeMastered(id) {
  try {
    await learnApi.toggleMistake(id)
    await loadMistakeAll()
    await loadClusters()
  } catch (e) {
    app.toastMsg('操作失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function removeMistakeRow(id) {
  try {
    await learnApi.delMistake(id)
    app.toastMsg('已删除该错题', 'success')
    await loadMistakeAll()
  } catch (e) {
    app.toastMsg('删除失败：' + (e?.message || '网络异常'), 'error')
  }
}

// ===== F523 每日学习目标 =====
const goal = ref({})
const goalInput = ref(30)
async function loadGoal() {
  try { goal.value = await learnApi.dailyGoal(); goalInput.value = goal.value.target_minutes || 30 } catch { goal.value = {} }
}
async function saveGoal() {
  if (!goalInput.value || goalInput.value < 1) return app.toastMsg('请填写有效的目标分钟', 'warn')
  goal.value = await learnApi.saveDailyGoal({ target_minutes: Number(goalInput.value) })
  app.toastMsg('今日目标已更新', 'success')
}

// ===== F524 番茄钟专注闭环 =====
const pomoStat = ref({})
const pomoState = reactive({ mode: 'work', running: false, remain: 25 * 60, workMin: 25, breakMin: 5, round: 0, marked: false })
let pomoTimer = null
let pomoDisposed = false
const pomoClock = computed(() => {
  const m = Math.floor(pomoState.remain / 60), s = pomoState.remain % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})
function tickPomo() {
  if (pomoState.remain > 0) { pomoState.remain--; return }
  if (pomoState.mode !== 'work') {
    // 休息结束，自动开始下一轮专注
    pomoState.mode = 'work'; pomoState.remain = pomoState.workMin * 60; pomoState.marked = false
    return
  }
  // 专注倒计时走完：先停表，记录后进入休息（避免 await 期间重复触发）
  clearInterval(pomoTimer); pomoTimer = null; pomoState.running = false
  const interrupted = pomoState.marked
  void (async () => {
    try {
      await learnApi.pomodoroSave({ minutes: pomoState.workMin, interrupted })
    } catch { /* 记录失败不阻塞进入休息 */ }
    if (pomoDisposed) return  // 组件已卸载：不再建表/改状态，防止幽灵计时
    pomoState.round++
    pomoState.mode = 'break'; pomoState.remain = pomoState.breakMin * 60; pomoState.marked = false
    pomoState.running = true; pomoTimer = setInterval(tickPomo, 1000)
    await loadPomoStat(); await loadSessions()
  })()
}
function togglePomo() {
  pomoState.running = !pomoState.running
  if (pomoState.running) { pomoTimer = setInterval(tickPomo, 1000) }
  else { clearInterval(pomoTimer); pomoTimer = null }
}
function resetPomo() {
  clearInterval(pomoTimer); pomoTimer = null
  pomoState.running = false; pomoState.mode = 'work'
  pomoState.remain = pomoState.workMin * 60; pomoState.marked = false
}
function markPomoInterrupt() { pomoState.marked = true; app.toastMsg('已标记本轮被打断', 'warn') }
async function finishPomoNow() {
  const worked = pomoState.workMin * 60 - pomoState.remain
  if (worked <= 0) return app.toastMsg('还没开始专注', 'warn')
  clearInterval(pomoTimer); pomoTimer = null; pomoState.running = false
  if (worked < 60 && !pomoState.marked) return app.toastMsg('专注不足 1 分钟，未记录', 'warn')
  const minutes = Math.max(1, Math.round(worked / 60))
  await learnApi.pomodoroSave({ minutes, interrupted: pomoState.marked })
  resetPomo()
  await loadPomoStat(); await loadSessions()
  app.toastMsg('本轮已记录', 'success')
}
async function loadPomoStat() { try { pomoStat.value = await learnApi.pomodoro() } catch { pomoStat.value = {} } }

// ===== F546 学习计划排程解释 =====
const planExplain = reactive({})
async function onPlanToggle(p) {
  if (planExplain[p.id]) return
  const d = await learnApi.planDetail(p.id)
  planExplain[p.id] = d.explain
}

// ===== F540 学习徽章 =====
const badges = ref({})
async function loadBadges() {
  const d = await learnApi.learningBadges()
  badges.value = d
  if (d.new && d.new.length) app.toastMsg(`新解锁 ${d.new.length} 枚徽章`, 'success')
}

// ===== F522 连续打卡 streak =====
const streak = ref({})
const streakCells = computed(() => {
  const set = new Set(streak.value.days || [])
  const arr = []
  for (let i = 20; i >= 0; i--) {
    const d = new Date(new Date().getTime() - i * 86400000)
    const iso = d.toISOString().slice(0, 10)
    arr.push({ date: iso, on: set.has(iso), today: i === 0 })
  }
  return arr
})
async function loadStreak() {
  try { streak.value = await learnApi.studyStreak() } catch { streak.value = {} }
}

// ===== F521 艾宾浩斯复习队列 =====
const rqData = ref(null)
const rqCount = computed(() => (rqData.value?.words?.length || 0) + (rqData.value?.mistakes?.length || 0))
async function loadReviewQueue() {
  try { rqData.value = await learnApi.reviewQueue() } catch { rqData.value = { words: [], mistakes: [] } }
}
async function markReview(kind, id) {
  await learnApi.reviewMark(kind, id)
  app.toastMsg('已标记复习，已推迟到下一个复习点', 'success')
  if (kind === 'word') rqData.value.words = (rqData.value.words || []).filter((w) => w.id !== id)
  else rqData.value.mistakes = (rqData.value.mistakes || []).filter((m) => m.id !== id)
}

// ===== F519 月度学习报告 =====
const repMonth = ref(new Date().toISOString().slice(0, 7))
const report = ref(null)
async function genReport() {
  report.value = await learnApi.studyReport(repMonth.value)
  app.toastMsg('报告已生成', 'success')
}
function downloadReport() {
  if (!report.value) return
  const blob = new Blob([report.value.markdown], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = '学习报告-' + repMonth.value + '.md'
  a.click()
  URL.revokeObjectURL(a.href)
}

// ===== F533 学习数据导出 / 导入 =====
async function exportBackup() {
  const data = await learnApi.backupExport()
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = '学习数据备份-' + new Date().toISOString().slice(0, 10) + '.json'
  a.click()
  URL.revokeObjectURL(a.href)
  app.toastMsg('备份已导出', 'success')
}
async function importBackup(e) {
  const file = e.target.files[0]
  if (!file) return
  if (!window.confirm('将把该备份中的条目导入当前账号（只新建、不覆盖），确认继续？')) { e.target.value = ''; return }
  try {
    const data = JSON.parse(await file.text())
    const r = await learnApi.backupImport(data)
    app.toastMsg('导入完成：' + JSON.stringify(r.created || r), 'success')
  } catch (err) {
    app.toastMsg('导入失败：' + (err.message || err), 'error')
  }
  e.target.value = ''
}

// ===== F520 错题重练 =====
const redrillList = ref([])
const ansMap = reactive({})
const resMap = reactive({})
const resultOf = (id) => resMap[id]
const redrillAnswered = computed(() => Object.keys(resMap).length)
const redrillCorrectCount = computed(() => Object.values(resMap).filter((r) => r.correct).length)
function typeName(t) { return ({ single: '单选', judge: '判断', fill: '填空' })[t] || t }
async function loadReDrill() {
  const d = await learnApi.reDrill({ n: 10 })
  redrillList.value = d.list || []
}
async function submitReDrill(m, ans) {
  if (ans === undefined || ans === '') return app.toastMsg('请先作答', 'warn')
  const r = await learnApi.reDrillSubmit(m.id, ans)
  resMap[m.id] = r
  app.toastMsg(r.correct ? '答对了' : '已记录，看参考答案', r.correct ? 'success' : 'warn')
}
async function masterReDrill(m) {
  await learnApi.toggleMistake(m.id)
  redrillList.value = redrillList.value.filter((x) => x.id !== m.id)
  app.toastMsg('已标记掌握', 'success')
}

// ===== F541 弱项雷达（手写 SVG，不引 ECharts）=====
const weakness = ref({})
const weakMode = ref('subject')
async function loadWeakness() {
  try { weakness.value = await learnApi.weaknessRadar() } catch { weakness.value = {} }
}
const SUBJECT_CN = {
  chinese: '语文', math: '数学', english: '英语', physics: '物理', chemistry: '化学',
  biology: '生物', history: '历史', geography: '地理', politics: '道德与法治', science: '科学', society: '社会',
}
const WK = { x: 150, y: 118, r: 84 }
const wkPt = (deg, r) => { const a = deg * Math.PI / 180; return { x: WK.x + r * Math.cos(a), y: WK.y + r * Math.sin(a) } }
const weakAxes = computed(() => {
  const isSubj = weakMode.value === 'subject'
  const src = isSubj ? weakness.value.by_subject : weakness.value.by_type
  return (src || []).map((it) => {
    const raw = it.name ?? it.label ?? ''
    return { name: isSubj ? (SUBJECT_CN[raw] ?? raw) : raw, rate: Number(it.fixed_rate ?? 0), weak: !!it.weak }
  }).slice().sort((a, b) => a.rate - b.rate).slice(0, 8)
})
// 后端 order 是学科名字符串数组（如 ["chinese"]），映射到 by_subject 取订正率并翻译成中文名
const weakOrder = computed(() => {
  const subj = weakness.value.by_subject || []
  return (weakness.value.order || []).map((o) => {
    const raw = typeof o === 'string' ? o : (o.name ?? '')
    const hit = subj.find((s) => s.name === raw)
    const rate = hit ? Number(hit.fixed_rate ?? 0) : (typeof o === 'object' ? Number(o.fixed_rate ?? 0) : 0)
    const weak = hit ? !!hit.weak : (typeof o === 'object' ? !!o.weak : true)
    return { name: SUBJECT_CN[raw] ?? raw, fixed_rate: rate, weak }
  })
})
function wkRing(scale) {
  const n = weakAxes.value.length
  return weakAxes.value.map((_, i) => {
    const p = wkPt(-90 + i * 360 / n, WK.r * scale / 100)
    return p.x.toFixed(1) + ',' + p.y.toFixed(1)
  }).join(' ')
}
const weakRings = computed(() => [25, 50, 75, 100].map(v => ({ v, pts: wkRing(v) })))
const weakSpokes = computed(() => weakAxes.value.map((_, i) => {
  const n = weakAxes.value.length, p = wkPt(-90 + i * 360 / n, WK.r)
  return { x1: WK.x, y1: WK.y, x2: p.x.toFixed(1), y2: p.y.toFixed(1) }
}))
const weakDots = computed(() => weakAxes.value.map((ax, i) => {
  const n = weakAxes.value.length
  const p = wkPt(-90 + i * 360 / n, WK.r * Math.min(100, Math.max(0, ax.rate)) / 100)
  return { x: p.x.toFixed(1), y: p.y.toFixed(1), weak: ax.weak }
}))
const weakDataPts = computed(() => weakDots.value.map(d => d.x + ',' + d.y).join(' '))
const weakLabels = computed(() => weakAxes.value.map((ax, i) => {
  const n = weakAxes.value.length, p = wkPt(-90 + i * 360 / n, WK.r + 16)
  let anchor = 'middle'
  if (p.x > WK.x + 6) anchor = 'start'; else if (p.x < WK.x - 6) anchor = 'end'
  const nm = ax.name.length > 6 ? ax.name.slice(0, 6) + '…' : ax.name
  return { x: p.x.toFixed(1), y: (p.y + 3.5).toFixed(1), anchor, nm, rate: Math.round(ax.rate), weak: ax.weak }
}))

// ===== 学习概览（#83 #84 #85）=====
const todayMin = ref(0), weekMin = ref(0), monthMin = ref(0)
const trend14 = ref([]), maxTrend = ref(1)
const calYear = ref(new Date().getFullYear()), calMonth = ref(new Date().getMonth())
const dayMap = ref({})
const calendarCells = computed(() => {
  const y = calYear.value, m = calMonth.value
  const first = new Date(y, m, 1)
  let startWeekday = (first.getDay() + 6) % 7 // 周一为 0
  const daysInMonth = new Date(y, m + 1, 0).getDate()
  const cells = []
  for (let i = 0; i < startWeekday; i++) cells.push({ day: '', minutes: 0 })
  for (let d = 1; d <= daysInMonth; d++) {
    const iso = `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, minutes: dayMap.value[iso] || 0 })
  }
  return cells
})
function shiftMonth(d) {
  let m = calMonth.value + d, y = calYear.value
  if (m < 0) { m = 11; y-- }
  if (m > 11) { m = 0; y++ }
  calMonth.value = m; calYear.value = y
}
async function loadOverview() {
  const data = await learnApi.sessions()
  const list = data.list || []
  dayMap.value = {}
  list.forEach(s => { dayMap.value[s.study_date] = (dayMap.value[s.study_date] || 0) + (s.minutes || 0) })
  const now = new Date()
  const iso = (dt) => dt.toISOString().slice(0, 10)
  const t = iso(now)
  todayMin.value = dayMap.value[t] || 0
  const wk = dayMap.value[t] || 0
  weekMin.value = 0; monthMin.value = 0
  trend14.value = []
  for (let i = 13; i >= 0; i--) {
    const d = new Date(now - i * 86400000)
    const key = iso(d)
    const min = dayMap.value[key] || 0
    trend14.value.push({ date: key, minutes: min })
    if (i < 7) weekMin.value += min
    if (d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) monthMin.value += min
  }
  maxTrend.value = Math.max(...trend14.value.map(x => x.minutes), 1)
}

async function switchTab(v) {
  tab.value = v
  if (v === 'overview') {
    await loadOverview(); await loadGoal(); await loadBadges(); await loadWeakness()
    await loadStreak(); await loadReviewQueue()
    await loadForecast(); await loadPref(); await loadExams(); await loadUsage()
  }
  if (v === 'progress') { await loadProgress(); await loadHeatmap(); await loadClusters() }
  if (v === 'bookmark') await loadBookmarks()
  if (v === 'session') { await loadSessions(); await loadPomoStat() }
  if (v === 'plan') await loadPlans()
  if (v === 'redrill') await loadReDrill()
  if (v === 'mistake') await loadMistakeAll()
}

onMounted(() => {
  loadOverview(); loadGoal(); loadBadges(); loadWeakness(); loadStreak(); loadReviewQueue()
  loadForecast(); loadPref(); loadExams(); loadUsage()
})

onUnmounted(() => {
  pomoDisposed = true
  clearInterval(pomoTimer)
  pomoTimer = null
})
</script>
