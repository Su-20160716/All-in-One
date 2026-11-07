<template>
  <div class="space-y-3">
    <!-- 子页签 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="p in PANELS"
          :key="p.key"
          class="rounded-pill px-3 py-1.5 text-[12px]"
          :class="panel === p.key ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          @click="switchPanel(p.key)"
        >
          {{ p.label }}
        </button>
        <span class="ml-2 tag">{{ scopeLabel }}</span>
        <span v-if="!rulesetId" class="tag bg-amber-50 text-amber-600">需要选择规则集</span>
        <button v-else class="btn-ghost ml-auto py-1 text-[11px]" @click="emit('go', 'rulesets')">维护规则</button>
      </div>
      <p class="mt-2 text-[11px] text-ink-400">{{ panelHint }}</p>
    </div>

    <!-- 单条评估 -->
    <div v-if="panel === 'single'" class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="输入事实" subtitle="JSON 对象，字段路径对应条件里的 facts.xxx">
        <template #actions>
          <button class="btn-ghost py-1 text-[11px]" @click="fillSingleSample">载入示例</button>
        </template>
        <textarea v-model="singleFacts" class="input min-h-[180px] font-mono text-[12px]" placeholder='{"amount": 1500}'></textarea>
        <div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            变量覆盖（可选）
            <input v-model="singleVars" class="input py-1 font-mono text-[12px]" placeholder='{"riskLevel": "high"}' />
          </label>
          <div class="flex flex-col gap-1.5 pt-4 text-[12px] text-ink-600">
            <label class="flex items-center gap-1.5">
              <input v-model="singleExplain" type="checkbox" class="h-3.5 w-3.5" />
              返回条件追踪（explain）
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="singlePersist" type="checkbox" class="h-3.5 w-3.5" />
              落库评估记录
            </label>
          </div>
        </div>
        <div v-if="singleError" class="mt-2 rounded-control bg-rose-50 px-2 py-2 text-[12px] text-rose-600">{{ singleError }}</div>
        <button class="btn-primary mt-3 w-full" :disabled="singleRunning || !rulesetId" @click="runSingle">
          {{ singleRunning ? '评估中…' : '执行单条评估' }}
        </button>
        <p v-if="!rulesetId" class="mt-2 text-[11px] text-amber-600">请先在页面顶部选择规则集</p>
      </SectionCard>

      <SectionCard title="评估结果" subtitle="决策、命中规则、耗时与动作输出">
        <div v-if="singleRunning" class="py-12 text-center text-[12px] text-ink-400">评估中…</div>
        <div v-else-if="!singleResult" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
          填写事实后执行评估，结果在这里展示
        </div>
        <template v-else>
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag" :class="singleResult.matched ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
              {{ singleResult.matched ? '命中' : '未命中' }}
            </span>
            <span class="tag">{{ singleResult.status }}</span>
            <span class="tag">决策 {{ singleResult.decision?.decision || 'no_match' }}</span>
            <span class="tag">{{ fmtMs(singleResult.duration_ms) }}</span>
            <span v-if="singleResult.evaluation_id" class="text-[11px] text-ink-400">记录 #{{ singleResult.evaluation_id }}</span>
          </div>
          <div v-if="singleResult.errors?.length" class="mt-2 space-y-1">
            <div v-for="(err, i) in singleResult.errors" :key="`se-${i}`" class="rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
              {{ err.rule_name || err.rule_id }}：{{ err.error }}
            </div>
          </div>
          <div class="mt-2">
            <div class="mb-1 text-[12px] font-medium text-ink-600">命中规则</div>
            <div v-if="!singleResult.decision?.rules?.length" class="text-[12px] text-ink-400">无</div>
            <div v-else class="flex flex-wrap gap-1">
              <span v-for="rule in singleResult.decision.rules" :key="rule.id" class="tag-brand">
                {{ rule.name }} · P{{ rule.priority }}
              </span>
            </div>
          </div>
          <div class="mt-2">
            <div class="mb-1 text-[12px] font-medium text-ink-600">输出</div>
            <pre class="max-h-[150px] overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ pretty(singleResult.decision?.outputs) }}</pre>
          </div>
          <div class="mt-2">
            <div class="mb-1 text-[12px] font-medium text-ink-600">动作执行</div>
            <div v-if="!singleResult.decision?.actions?.length" class="text-[12px] text-ink-400">无动作执行</div>
            <div v-else class="space-y-1">
              <div v-for="(act, i) in singleResult.decision.actions" :key="`sa-${i}`" class="flex flex-wrap items-center gap-1.5 rounded-control bg-ink-50/60 px-2 py-1 text-[11px]">
                <span class="tag">{{ act.type || act.action_type || 'action' }}</span>
                <span class="tag" :class="act.status === 'success' ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                  {{ act.status || '—' }}
                </span>
                <span class="min-w-0 flex-1 break-all text-ink-500">{{ act.error || summarize(act.output) }}</span>
              </div>
            </div>
          </div>
        </template>
      </SectionCard>

      <SectionCard class="lg:col-span-2" title="条件追踪" subtitle="每条规则的表达式、逐步求值与条件树">
        <div v-if="singleRunning" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!singleTraces.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
          暂无追踪数据，勾选「返回条件追踪」后重新评估
        </div>
        <div v-else class="space-y-2">
          <div v-for="rule in singleTraces" :key="rule.rule_id" class="rounded-control border border-ink-100">
            <button class="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left" @click="toggleTrace(rule.rule_id)">
              <span class="tag" :class="rule.matched ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                {{ rule.matched ? '命中' : '未命中' }}
              </span>
              <span class="min-w-0 flex-1 truncate text-[13px] text-ink-800">{{ rule.name }}</span>
              <span class="text-[11px] text-ink-400">P{{ rule.priority }} · {{ fmtMs(rule.duration_ms) }}</span>
              <span class="text-[11px] text-ink-400">{{ openTraces.includes(rule.rule_id) ? '收起' : '展开' }}</span>
            </button>
            <div v-if="openTraces.includes(rule.rule_id)" class="border-t border-ink-50 px-3 py-2">
              <div v-if="rule.error" class="mb-2 rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">{{ rule.error }}</div>
              <div class="mb-2 break-all rounded-control bg-ink-50/60 px-2 py-1 font-mono text-[11px] text-ink-600">
                {{ rule.expression || '（无表达式）' }}
              </div>
              <div class="grid gap-2 lg:grid-cols-2">
                <div>
                  <div class="mb-1 text-[11px] font-medium text-ink-500">求值步骤</div>
                  <div v-if="!rule.trace?.steps?.length" class="text-[11px] text-ink-400">无步骤</div>
                  <div v-else class="max-h-[200px] overflow-auto rounded-control border border-ink-100">
                    <table class="w-full">
                      <thead class="bg-ink-50/60">
                        <tr>
                          <th class="th">#</th>
                          <th class="th">节点</th>
                          <th class="th">表达式</th>
                          <th class="th">值</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-ink-50">
                        <tr v-for="step in rule.trace.steps" :key="step.seq">
                          <td class="td text-[11px]">{{ step.seq }}</td>
                          <td class="td text-[11px]">{{ step.kind }}</td>
                          <td class="td max-w-[220px] truncate font-mono text-[11px]">{{ step.expr }}</td>
                          <td class="td text-[11px]">
                            <span :class="step.bool === false ? 'text-rose-600' : 'text-ink-600'">{{ summarize(step.value) }}</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
                <div>
                  <div class="mb-1 text-[11px] font-medium text-ink-500">条件树</div>
                  <div v-if="!rule.trace?.tree" class="text-[11px] text-ink-400">无树结构</div>
                  <div v-else class="max-h-[200px] overflow-auto rounded-control bg-ink-50/60 p-2 font-mono text-[11px] text-ink-600">
                    <div
                      v-for="line in treeLines(rule.trace.tree)"
                      :key="`${rule.rule_id}-${line.key}`"
                      :style="{ paddingLeft: `${line.depth * 12}px` }"
                      class="whitespace-pre-wrap"
                    >
                      {{ line.text }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>

    <!-- 批量仿真 -->
    <div v-else-if="panel === 'batch'" class="space-y-3">
      <div class="grid gap-3 lg:grid-cols-2">
        <SectionCard title="批量事实" subtitle="JSON 数组，每条为对象，最多 200 条">
          <template #actions>
            <button class="btn-ghost py-1 text-[11px]" @click="fillBatchSample">载入示例</button>
          </template>
          <textarea v-model="batchFacts" class="input min-h-[170px] font-mono text-[12px]" placeholder='[{"amount": 100}, {"amount": 2000}]'></textarea>
          <label class="mt-2 flex items-center gap-1.5 text-[12px] text-ink-600">
            <input v-model="batchPersist" type="checkbox" class="h-3.5 w-3.5" />
            落库评估记录
          </label>
          <div v-if="batchError" class="mt-2 rounded-control bg-rose-50 px-2 py-2 text-[12px] text-rose-600">{{ batchError }}</div>
          <button class="btn-primary mt-3 w-full" :disabled="batchRunning || !rulesetId" @click="runBatch">
            {{ batchRunning ? '仿真中…' : '运行批量仿真' }}
          </button>
          <p v-if="!rulesetId" class="mt-2 text-[11px] text-amber-600">请先在页面顶部选择规则集</p>
        </SectionCard>

        <SectionCard title="仿真摘要" subtitle="命中率、耗时与逐条结果">
          <div v-if="batchRunning" class="py-12 text-center text-[12px] text-ink-400">仿真运行中…</div>
          <div v-else-if="!batchResult" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
            运行后在右侧查看摘要与命中分布
          </div>
          <template v-else>
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
                <div class="text-[10px] text-ink-400">总数</div>
                <div class="text-[15px] font-semibold text-ink-800">{{ batchResult.total }}</div>
              </div>
              <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
                <div class="text-[10px] text-ink-400">命中</div>
                <div class="text-[15px] font-semibold text-emerald-600">{{ batchResult.matched }}</div>
              </div>
              <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
                <div class="text-[10px] text-ink-400">错误</div>
                <div class="text-[15px] font-semibold" :class="batchResult.errors ? 'text-rose-600' : 'text-ink-800'">{{ batchResult.errors }}</div>
              </div>
              <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
                <div class="text-[10px] text-ink-400">平均耗时</div>
                <div class="text-[15px] font-semibold text-ink-800">{{ fmtMs(batchResult.duration?.avg) }}</div>
              </div>
            </div>
            <div class="mt-3">
              <div class="mb-1 text-[12px] font-medium text-ink-600">命中分布</div>
              <BarChart v-if="batchDistribution.length" :data="batchDistribution" horizontal :height="150" />
              <div v-else class="rounded-control border border-dashed border-ink-200 py-4 text-center text-[12px] text-ink-400">
                本次仿真没有规则命中
              </div>
            </div>
            <div class="mt-2">
              <div class="mb-1 text-[12px] font-medium text-ink-600">逐条结果</div>
              <div class="max-h-[180px] overflow-auto rounded-control border border-ink-100">
                <table class="w-full">
                  <thead class="bg-ink-50/60">
                    <tr>
                      <th class="th">#</th>
                      <th class="th">命中</th>
                      <th class="th">决策</th>
                      <th class="th">规则</th>
                      <th class="th">耗时</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-ink-50">
                    <tr v-for="item in batchResult.items" :key="item.index">
                      <td class="td text-[11px]">{{ item.index + 1 }}</td>
                      <td class="td text-[11px]">
                        <span :class="item.matched ? 'text-emerald-600' : 'text-ink-400'">{{ item.matched ? '是' : '否' }}</span>
                      </td>
                      <td class="td text-[11px]">{{ item.error ? '异常' : (item.decision || 'no_match') }}</td>
                      <td class="td max-w-[180px] truncate text-[11px]">{{ (item.rules || []).join('、') || item.error || '—' }}</td>
                      <td class="td text-[11px]">{{ fmtMs(item.duration_ms) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>
        </SectionCard>
      </div>

      <SectionCard title="历史仿真" subtitle="持久化仿真记录与命中摘要">
        <template #actions>
          <button class="btn-ghost py-1 text-[11px]" :disabled="simLoading" @click="loadSimulations">刷新</button>
        </template>
        <div v-if="simLoading && !simulations.length" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="simError" class="flex items-center gap-2 rounded-control bg-rose-50 px-2 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ simError }}</span>
          <button class="shrink-0 font-medium" @click="loadSimulations">重试</button>
        </div>
        <div v-else-if="!simulations.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
          暂无历史仿真记录
        </div>
        <div v-else class="divide-y divide-ink-50">
          <button
            v-for="sim in simulations"
            :key="sim.id"
            class="flex w-full flex-wrap items-center gap-2 py-2 text-left hover:bg-ink-50/60"
            @click="openSimulation(sim)"
          >
            <span class="tag">{{ sim.status }}</span>
            <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ sim.name }}</span>
            <span class="text-[11px] text-ink-400">{{ sim.fact_count }} 条</span>
            <span class="text-[11px] text-ink-400">命中率 {{ fmtPercent(sim.summary?.match_rate) }}</span>
            <span class="text-[11px] text-ink-400">{{ fmtMs(sim.duration_ms) }}</span>
            <span class="w-28 text-right text-[11px] text-ink-400">{{ fmtDate(sim.created_at, true) }}</span>
          </button>
        </div>
      </SectionCard>
    </div>

    <!-- 测试用例 -->
    <div v-else-if="panel === 'cases'" class="space-y-3">
      <div class="card flex flex-wrap items-end gap-2 p-3">
        <label class="flex min-w-[160px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
          关键词
          <input v-model="caseQ" class="input" placeholder="用例名称" @keyup.enter="applyCaseFilters" />
        </label>
        <label class="flex w-[130px] flex-col gap-1 text-[11px] text-ink-500">
          结果
          <select v-model="caseStatus" class="input" @change="applyCaseFilters">
            <option value="">全部</option>
            <option value="passed">通过</option>
            <option value="failed">失败</option>
          </select>
        </label>
        <button class="btn-outline" :disabled="casesLoading" @click="applyCaseFilters">查询</button>
        <button class="btn-ghost" :disabled="!rulesetId || runAllLoading" @click="runAllCases">
          {{ runAllLoading ? '运行中…' : '运行全部用例' }}
        </button>
        <button class="btn-primary ml-auto" :disabled="!rulesetId" @click="openCaseCreate">新建用例</button>
      </div>

      <div v-if="!rulesetId" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
        测试用例必须归属某个规则集，请先在页面顶部选择规则集。
      </div>
      <div v-if="runAllResult" class="rounded-control bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
        批量运行完成：共 {{ runAllResult.total }} 条，通过 {{ runAllResult.passed }}，失败 {{ runAllResult.failed }}，通过率 {{ fmtPercent(runAllResult.pass_rate) }}
      </div>

      <div class="card overflow-hidden">
        <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2">
          <span class="text-[13px] font-medium text-ink-700">测试用例</span>
          <span class="text-[11px] text-ink-400">共 {{ caseTotal }} 条 · 第 {{ casePage }}/{{ casePages }} 页</span>
        </div>
        <div v-if="casesLoading && !cases.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="casesError" class="flex items-center gap-3 bg-rose-50 px-3 py-3 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ casesError }}</span>
          <button class="shrink-0 font-medium" @click="loadCases">重试</button>
        </div>
        <div v-else-if="!cases.length" class="px-3 py-10 text-center text-[12px] text-ink-400">
          还没有测试用例，新建后用固定事实回归规则
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[820px]">
            <thead class="bg-ink-50/60">
              <tr>
                <th class="th">用例</th>
                <th class="th">输入事实</th>
                <th class="th">期望输出</th>
                <th class="th">结果</th>
                <th class="th">最后运行</th>
                <th class="th text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in cases" :key="row.id" class="hover:bg-ink-50/50">
                <td class="td">
                  <div class="max-w-[200px] truncate font-medium text-ink-800">{{ row.name }}</div>
                  <div class="text-[11px] text-ink-400">#{{ row.id }}</div>
                </td>
                <td class="td max-w-[200px] truncate font-mono text-[11px] text-ink-500">{{ summarize(row.facts) }}</td>
                <td class="td max-w-[180px] truncate font-mono text-[11px] text-ink-500">{{ summarize(row.expected) }}</td>
                <td class="td">
                  <span class="tag" :class="row.passed ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                    {{ row.passed ? '通过' : '未通过' }}
                  </span>
                </td>
                <td class="td text-[11px] text-ink-400">{{ fmtDate(row.last_run_at, true) }}</td>
                <td class="td">
                  <div class="flex justify-end gap-1">
                    <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="caseRunning === row.id" @click="runCase(row)">
                      {{ caseRunning === row.id ? '运行中…' : '运行' }}
                    </button>
                    <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openCaseEdit(row)">编辑</button>
                    <button class="btn-ghost px-2 py-0.5 text-[11px] text-rose-600" @click="deleteCase(row)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex items-center justify-between border-t border-ink-100 px-3 py-2">
          <span class="text-[11px] text-ink-400">每页 {{ casePageSize }} 条</span>
          <div class="flex items-center gap-1">
            <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="casePage <= 1 || casesLoading" @click="goCasePage(casePage - 1)">上一页</button>
            <span class="px-2 text-[12px] text-ink-500">{{ casePage }} / {{ casePages }}</span>
            <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="casePage >= casePages || casesLoading" @click="goCasePage(casePage + 1)">下一页</button>
          </div>
        </div>
      </div>

      <SectionCard v-if="caseResult" title="用例运行结果" subtitle="实际输出与期望逐字段比对">
        <template #actions>
          <button class="btn-ghost py-1 text-[11px]" @click="caseResult = null">关闭</button>
        </template>
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag" :class="caseResult.passed ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
            {{ caseResult.passed ? '通过' : '未通过' }}
          </span>
          <span class="tag">{{ caseResult.status }}</span>
          <span class="tag">{{ fmtMs(caseResult.duration_ms) }}</span>
          <span class="text-[11px] text-ink-400">{{ caseResult.name }}</span>
        </div>
        <div v-if="caseResult.checks?.length" class="mt-2 divide-y divide-ink-50">
          <div v-for="check in caseResult.checks" :key="check.field" class="flex flex-wrap items-center gap-2 py-1.5 text-[12px]">
            <span class="tag" :class="check.ok ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
              {{ check.ok ? '一致' : '不一致' }}
            </span>
            <span class="font-mono text-ink-700">{{ check.field }}</span>
            <span class="text-ink-400">期望 {{ summarize(check.expected) }}</span>
            <span class="text-ink-400">实际 {{ summarize(check.actual) }}</span>
            <span v-if="check.reason" class="text-ink-400">{{ check.reason }}</span>
          </div>
        </div>
        <div v-else class="mt-2 text-[12px] text-ink-400">没有比对项</div>
      </SectionCard>
    </div>

    <!-- 冲突检测 -->
    <div v-else class="space-y-3">
      <div class="card flex flex-wrap items-center gap-2 p-3">
        <span class="text-[12px] text-ink-500">检测重复、重叠、不可达与动作矛盾规则</span>
        <select v-model="conflictStatus" class="input w-[130px] py-1 text-[12px]" @change="loadConflicts">
          <option value="">全部状态</option>
          <option value="open">待处理</option>
          <option value="resolved">已解决</option>
          <option value="ignored">已忽略</option>
        </select>
        <select v-model="conflictSeverity" class="input w-[130px] py-1 text-[12px]" @change="loadConflicts">
          <option value="">全部严重度</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
        <button class="btn-outline" :disabled="conflictLoading" @click="loadConflicts">刷新</button>
        <button class="btn-primary ml-auto" :disabled="!rulesetId || detecting" @click="detectConflicts">
          {{ detecting ? '检测中…' : '立即检测' }}
        </button>
      </div>

      <div v-if="!rulesetId" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
        冲突检测以规则集为单位，请先在页面顶部选择规则集。
      </div>
      <div v-if="detectNotice" class="rounded-control bg-brand-50 px-3 py-2 text-[12px] text-brand-700">{{ detectNotice }}</div>

      <div class="card overflow-hidden">
        <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2">
          <span class="text-[13px] font-medium text-ink-700">冲突记录</span>
          <span class="text-[11px] text-ink-400">共 {{ conflictTotal }} 条</span>
        </div>
        <div v-if="conflictLoading && !conflicts.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="conflictError" class="flex items-center gap-3 bg-rose-50 px-3 py-3 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ conflictError }}</span>
          <button class="shrink-0 font-medium" @click="loadConflicts">重试</button>
        </div>
        <div v-else-if="!conflicts.length" class="px-3 py-10 text-center text-[12px] text-ink-400">
          当前没有冲突记录，可点击「立即检测」重新扫描
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[860px]">
            <thead class="bg-ink-50/60">
              <tr>
                <th class="th">类型</th>
                <th class="th">严重度</th>
                <th class="th">规则</th>
                <th class="th">原因</th>
                <th class="th">状态</th>
                <th class="th">发现时间</th>
                <th class="th text-right">处理</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in conflicts" :key="row.id">
                <td class="td"><span class="tag">{{ conflictTypeLabel(row.conflict_type) }}</span></td>
                <td class="td">
                  <span class="tag" :class="severityClass(row.severity)">{{ severityLabel(row.severity) }}</span>
                </td>
                <td class="td max-w-[190px] truncate text-[12px]">
                  {{ row.rule_a?.name || '—' }} vs {{ row.rule_b?.name || '—' }}
                </td>
                <td class="td max-w-[280px] truncate text-[11px] text-ink-500">{{ row.detail?.reason || '—' }}</td>
                <td class="td"><span class="tag" :class="conflictStatusClass(row.status)">{{ conflictStatusLabel(row.status) }}</span></td>
                <td class="td text-[11px] text-ink-400">{{ fmtDate(row.created_at, true) }}</td>
                <td class="td">
                  <div class="flex justify-end gap-1">
                    <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="row.status !== 'open'" @click="closeConflict(row, 'resolve')">标记解决</button>
                    <button class="btn-ghost px-2 py-0.5 text-[11px]" :disabled="row.status !== 'open'" @click="closeConflict(row, 'ignore')">忽略</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 用例编辑 -->
    <Modal v-model="caseShow" :title="caseForm.id ? '编辑测试用例' : '新建测试用例'" width="680px">
      <div v-if="caseFormError" class="mb-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ caseFormError }}</div>
      <label class="flex flex-col gap-1 text-[12px] text-ink-600">
        用例名称
        <input v-model.trim="caseForm.name" class="input" placeholder="如 高额订单应进入复核" />
      </label>
      <label class="mt-2 flex flex-col gap-1 text-[12px] text-ink-600">
        输入事实（JSON 对象）
        <textarea v-model="caseForm.facts" class="input min-h-[110px] font-mono text-[12px]"></textarea>
      </label>
      <label class="mt-2 flex flex-col gap-1 text-[12px] text-ink-600">
        期望输出（JSON 对象，可空）
        <textarea v-model="caseForm.expected" class="input min-h-[90px] font-mono text-[12px]"></textarea>
      </label>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="caseShow = false">取消</button>
        <button class="btn-primary" :disabled="caseSaving" @click="saveCase">{{ caseSaving ? '保存中…' : '保存用例' }}</button>
      </div>
    </Modal>

    <!-- 历史仿真详情 -->
    <Modal v-model="simShow" :title="simDetail?.name || '仿真详情'" width="760px">
      <div v-if="simDetailLoading" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="simDetailError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ simDetailError }}</div>
      <template v-else-if="simDetail">
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[10px] text-ink-400">事实条数</div>
            <div class="text-[15px] font-semibold text-ink-800">{{ simDetail.summary?.total ?? simDetail.fact_count }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[10px] text-ink-400">命中</div>
            <div class="text-[15px] font-semibold text-emerald-600">{{ simDetail.summary?.matched ?? 0 }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[10px] text-ink-400">命中率</div>
            <div class="text-[15px] font-semibold text-ink-800">{{ fmtPercent(simDetail.summary?.match_rate) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[10px] text-ink-400">耗时</div>
            <div class="text-[15px] font-semibold text-ink-800">{{ fmtMs(simDetail.duration_ms) }}</div>
          </div>
        </div>
        <div class="mt-3">
          <div class="mb-1 text-[12px] font-medium text-ink-600">命中分布</div>
          <div v-if="simDetail.summary?.hit_distribution?.length" class="divide-y divide-ink-50">
            <div v-for="item in simDetail.summary.hit_distribution" :key="item.rule" class="flex items-center gap-2 py-1 text-[12px]">
              <span class="min-w-0 flex-1 truncate text-ink-700">{{ item.rule }}</span>
              <span class="text-ink-400">{{ item.count }} 次</span>
            </div>
          </div>
          <div v-else class="text-[12px] text-ink-400">无命中</div>
        </div>
        <div class="mt-3">
          <div class="mb-1 text-[12px] font-medium text-ink-600">样本</div>
          <pre class="max-h-[240px] overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ pretty(simDetail.results || []) }}</pre>
        </div>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Modal from '../../components/Modal.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import BarChart from '../../components/platform/BarChart.vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate } from '../../composables/useDomainResource'

const props = defineProps({
  rulesetId: { type: [String, Number], default: '' },
  rulesets: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['go'])
const api = apiFor('rules')
const app = useAppStore()

const PANELS = [
  { key: 'single', label: '单条评估', hint: '输入事实并查看决策、条件追踪与耗时' },
  { key: 'batch', label: '批量仿真', hint: '一次评估多条事实，观察命中分布与历史仿真' },
  { key: 'cases', label: '测试用例', hint: '维护固定事实与期望输出，批量回归规则' },
  { key: 'conflicts', label: '冲突检测', hint: '扫描重复、重叠、不可达与动作矛盾规则' },
]

const panel = ref('single')
const panelHint = computed(() => PANELS.find((item) => item.key === panel.value)?.hint || '')

const scopeLabel = computed(() => {
  if (!props.rulesetId) return '全部规则集'
  const found = props.rulesets.find((item) => String(item.id) === String(props.rulesetId))
  return found ? found.name : `规则集 #${props.rulesetId}`
})

const singleFacts = ref('{\n  "amount": 1500,\n  "channel": "app",\n  "level": "vip"\n}')
const singleVars = ref('')
const singleExplain = ref(true)
const singlePersist = ref(true)
const singleRunning = ref(false)
const singleError = ref('')
const singleResult = ref(null)
const openTraces = ref([])

const batchFacts = ref('[\n  { "amount": 80, "channel": "app" },\n  { "amount": 1500, "channel": "app" },\n  { "amount": 6000, "channel": "web" }\n]')
const batchPersist = ref(false)
const batchRunning = ref(false)
const batchError = ref('')
const batchResult = ref(null)

const simulations = ref([])
const simLoading = ref(false)
const simError = ref('')
const simShow = ref(false)
const simDetail = ref(null)
const simDetailLoading = ref(false)
const simDetailError = ref('')

const cases = ref([])
const caseQ = ref('')
const caseStatus = ref('')
const casePage = ref(1)
const casePageSize = ref(20)
const caseTotal = ref(0)
const casesLoading = ref(false)
const casesError = ref('')
const caseRunning = ref(null)
const runAllLoading = ref(false)
const runAllResult = ref(null)
const caseResult = ref(null)
const caseShow = ref(false)
const caseSaving = ref(false)
const caseFormError = ref('')
const caseForm = ref(emptyCaseForm())

const conflicts = ref([])
const conflictStatus = ref('')
const conflictSeverity = ref('')
const conflictTotal = ref(0)
const conflictLoading = ref(false)
const conflictError = ref('')
const detecting = ref(false)
const detectNotice = ref('')

const casePages = computed(() => Math.max(1, Math.ceil(caseTotal.value / Math.max(1, casePageSize.value))))

const singleTraces = computed(() => singleResult.value?.trace?.rules || [])

const batchDistribution = computed(() => {
  const counter = {}
  for (const item of batchResult.value?.items || []) {
    for (const name of item.rules || []) {
      counter[name] = (counter[name] || 0) + 1
    }
  }
  return Object.entries(counter)
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12)
})

function emptyCaseForm() {
  return { id: null, name: '', facts: '{}', expected: '{}' }
}

function pretty(value) {
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value, null, 2)
  } catch (e) {
    return String(value)
  }
}

function summarize(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value !== 'object') return String(value)
  try {
    const text = JSON.stringify(value)
    return text.length > 120 ? `${text.slice(0, 120)}…` : text
  } catch (e) {
    return String(value)
  }
}

function fmtDate(value, withTime = false) {
  return formatDate(value, withTime)
}

function fmtMs(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(n >= 100 ? 0 : 1)} ms`
}

function fmtPercent(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function isMissingEndpoint(e) {
  const s = e?.response?.status
  return s === 404 || s === 405 || s === 501
}

function parseJSON(text, label) {
  try {
    return text && text.trim() ? JSON.parse(text) : {}
  } catch (e) {
    throw new Error(`${label} JSON 解析失败`, { cause: e })
  }
}

function fillSingleSample() {
  singleFacts.value = JSON.stringify({ amount: 1500, channel: 'app', level: 'vip' }, null, 2)
}

function fillBatchSample() {
  batchFacts.value = JSON.stringify([
    { amount: 80, channel: 'app' },
    { amount: 1500, channel: 'app' },
    { amount: 6000, channel: 'web' },
  ], null, 2)
}

function toggleTrace(id) {
  if (openTraces.value.includes(id)) {
    openTraces.value = openTraces.value.filter((item) => item !== id)
  } else {
    openTraces.value = [...openTraces.value, id]
  }
}

function treeLines(node, depth = 0, out = []) {
  if (!node || typeof node !== 'object') return out
  const label = node.type || node.kind || 'node'
  const extra = []
  if (node.value !== undefined) extra.push(`= ${JSON.stringify(node.value)}`)
  if (node.path) extra.push(node.path)
  if (node.op) extra.push(`(${node.op})`)
  out.push({ key: out.length, depth, text: `${label} ${extra.join(' ')}`.trim() })
  const kids = node.children || node.args || node.items || []
  if (Array.isArray(kids)) {
    for (const child of kids) treeLines(child, depth + 1, out)
  }
  if (node.left) treeLines(node.left, depth + 1, out)
  if (node.right) treeLines(node.right, depth + 1, out)
  return out
}

function requireRuleSet() {
  if (!props.rulesetId) {
    app.toastMsg('请先在页面顶部选择规则集', 'error')
    return false
  }
  return true
}

async function runSingle() {
  if (!requireRuleSet()) return
  let facts
  let variables
  try {
    facts = parseJSON(singleFacts.value, '事实')
    variables = singleVars.value.trim() ? parseJSON(singleVars.value, '变量') : {}
  } catch (e) {
    singleError.value = e?.message || 'JSON 解析失败'
    return
  }
  singleRunning.value = true
  singleError.value = ''
  singleResult.value = null
  try {
    singleResult.value = await api.action('evaluate/', {
      ruleset_id: props.rulesetId,
      facts,
      variables,
      explain: singleExplain.value,
      persist: singlePersist.value,
    })
    openTraces.value = []
    app.toastMsg(singleResult.value?.matched ? '规则命中' : '未命中任何规则', 'success')
  } catch (e) {
    singleError.value = e?.message || '评估失败'
    app.toastMsg(singleError.value, 'error')
  } finally {
    singleRunning.value = false
  }
}

async function runBatch() {
  if (!requireRuleSet()) return
  let facts
  try {
    facts = parseJSON(batchFacts.value, '批量事实')
  } catch (e) {
    batchError.value = e?.message || 'JSON 解析失败'
    return
  }
  if (!Array.isArray(facts) || !facts.length) {
    batchError.value = '批量事实必须是 JSON 数组且至少一条'
    return
  }
  batchRunning.value = true
  batchError.value = ''
  batchResult.value = null
  try {
    batchResult.value = await api.action('evaluate/batch/', {
      ruleset_id: props.rulesetId,
      facts,
      persist: batchPersist.value,
    })
    app.toastMsg(`批量评估完成，命中 ${batchResult.value?.matched ?? 0} 条`, 'success')
    loadSimulations()
  } catch (e) {
    batchError.value = e?.message || '批量仿真失败'
    app.toastMsg(batchError.value, 'error')
  } finally {
    batchRunning.value = false
  }
}

async function loadSimulations() {
  if (!api) return
  simLoading.value = true
  simError.value = ''
  try {
    const params = { page: 1, page_size: 20 }
    if (props.rulesetId) params.ruleset_id = props.rulesetId
    const data = await api.list('simulations/', params)
    simulations.value = data.items || []
  } catch (e) {
    simulations.value = []
    if (isMissingEndpoint(e)) simError.value = '当前后端未提供仿真记录接口'
    else simError.value = e?.message || '仿真记录加载失败'
  } finally {
    simLoading.value = false
  }
}

async function openSimulation(sim) {
  simShow.value = true
  simDetail.value = null
  simDetailError.value = ''
  simDetailLoading.value = true
  try {
    simDetail.value = await api.get(`simulations/${sim.id}/`)
  } catch (e) {
    simDetailError.value = e?.message || '仿真详情加载失败'
  } finally {
    simDetailLoading.value = false
  }
}

function buildCaseParams() {
  const params = { page: casePage.value, page_size: casePageSize.value }
  if (props.rulesetId) params.ruleset_id = props.rulesetId
  if (caseQ.value.trim()) params.q = caseQ.value.trim()
  if (caseStatus.value) params.status = caseStatus.value
  return params
}

async function loadCases() {
  if (!api || !props.rulesetId) {
    cases.value = []
    caseTotal.value = 0
    return
  }
  casesLoading.value = true
  casesError.value = ''
  try {
    const data = await api.list('testcases/', buildCaseParams())
    cases.value = data.items || []
    caseTotal.value = Number(data.count) || 0
  } catch (e) {
    cases.value = []
    caseTotal.value = 0
    if (isMissingEndpoint(e)) casesError.value = '当前后端未提供测试用例接口'
    else casesError.value = e?.message || '测试用例加载失败'
  } finally {
    casesLoading.value = false
  }
}

function applyCaseFilters() {
  casePage.value = 1
  loadCases()
}

function goCasePage(next) {
  casePage.value = Math.min(Math.max(1, next), casePages.value)
  loadCases()
}

function openCaseCreate() {
  if (!requireRuleSet()) return
  caseForm.value = emptyCaseForm()
  caseFormError.value = ''
  caseShow.value = true
}

function openCaseEdit(row) {
  caseForm.value = {
    id: row.id,
    name: row.name || '',
    facts: pretty(row.facts || {}),
    expected: pretty(row.expected || {}),
  }
  caseFormError.value = ''
  caseShow.value = true
}

async function saveCase() {
  if (!caseForm.value.name.trim()) {
    caseFormError.value = '请填写用例名称'
    return
  }
  let facts
  let expected
  try {
    facts = parseJSON(caseForm.value.facts, '事实')
    expected = parseJSON(caseForm.value.expected, '期望输出')
  } catch (e) {
    caseFormError.value = e?.message || 'JSON 解析失败'
    return
  }
  caseSaving.value = true
  caseFormError.value = ''
  const payload = { name: caseForm.value.name.trim(), facts, expected, ruleset_id: props.rulesetId }
  try {
    if (caseForm.value.id) await api.action(`testcases/${caseForm.value.id}/update/`, payload)
    else await api.create('testcases/', payload)
    app.toastMsg(caseForm.value.id ? '用例已更新' : '用例已创建', 'success')
    caseShow.value = false
    await loadCases()
  } catch (e) {
    caseFormError.value = e?.message || '保存失败'
    app.toastMsg(caseFormError.value, 'error')
  } finally {
    caseSaving.value = false
  }
}

async function runCase(row) {
  caseRunning.value = row.id
  try {
    const result = await api.action(`testcases/${row.id}/run/`, {})
    caseResult.value = result
    app.toastMsg(result?.passed ? '用例通过' : '用例未通过', result?.passed ? 'success' : 'error')
    await loadCases()
  } catch (e) {
    app.toastMsg(e?.message || '运行失败', 'error')
  } finally {
    caseRunning.value = null
  }
}

async function runAllCases() {
  if (!requireRuleSet()) return
  runAllLoading.value = true
  runAllResult.value = null
  try {
    runAllResult.value = await api.action('testcases/run-all/', {
      ruleset_id: props.rulesetId,
      persist: true,
    })
    app.toastMsg(`已运行 ${runAllResult.value?.total ?? 0} 条用例`, 'success')
    await loadCases()
  } catch (e) {
    app.toastMsg(e?.message || '批量运行失败', 'error')
  } finally {
    runAllLoading.value = false
  }
}

async function deleteCase(row) {
  try {
    await api.action(`testcases/${row.id}/delete/`, {})
    app.toastMsg('用例已删除', 'success')
    await loadCases()
  } catch (e) {
    app.toastMsg(e?.message || '删除失败', 'error')
  }
}

function conflictTypeLabel(value) {
  const map = {
    duplicate: '条件重复',
    overlap: '条件重叠',
    unreachable: '不可达规则',
    contradiction: '动作冲突',
    shadowed: '被覆盖',
  }
  return map[value] || value || '—'
}

function severityLabel(value) {
  const map = { high: '高', medium: '中', low: '低' }
  return map[value] || value || '—'
}

function severityClass(value) {
  const map = {
    high: 'bg-rose-50 text-rose-600',
    medium: 'bg-amber-50 text-amber-600',
    low: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function conflictStatusLabel(value) {
  const map = { open: '待处理', resolved: '已解决', ignored: '已忽略' }
  return map[value] || value || '—'
}

function conflictStatusClass(value) {
  const map = {
    open: 'bg-rose-50 text-rose-600',
    resolved: 'bg-emerald-50 text-emerald-600',
    ignored: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

async function loadConflicts() {
  if (!api) return
  conflictLoading.value = true
  conflictError.value = ''
  try {
    const params = { page: 1, page_size: 100 }
    if (props.rulesetId) params.ruleset_id = props.rulesetId
    if (conflictStatus.value) params.status = conflictStatus.value
    if (conflictSeverity.value) params.severity = conflictSeverity.value
    const data = await api.list('conflicts/', params)
    conflicts.value = data.items || []
    conflictTotal.value = Number(data.count) || 0
  } catch (e) {
    conflicts.value = []
    conflictTotal.value = 0
    if (isMissingEndpoint(e)) conflictError.value = '当前后端未提供冲突检测接口'
    else conflictError.value = e?.message || '冲突记录加载失败'
  } finally {
    conflictLoading.value = false
  }
}

async function detectConflicts() {
  if (!requireRuleSet()) return
  detecting.value = true
  detectNotice.value = ''
  try {
    const result = await api.action('conflicts/detect/', {
      ruleset_id: props.rulesetId,
      persist: true,
    })
    detectNotice.value = `检测完成：发现 ${result?.count ?? 0} 处冲突，${result?.invalid_rules?.length ?? 0} 条规则表达式无法解析`
    app.toastMsg('冲突检测完成', 'success')
    await loadConflicts()
  } catch (e) {
    app.toastMsg(e?.message || '冲突检测失败', 'error')
  } finally {
    detecting.value = false
  }
}

async function closeConflict(row, action) {
  try {
    await api.action(`conflicts/${row.id}/${action}/`, { note: action === 'ignore' ? '工作台忽略' : '已人工处理' })
    app.toastMsg(action === 'ignore' ? '已忽略冲突' : '已标记解决', 'success')
    await loadConflicts()
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  }
}

function switchPanel(key) {
  panel.value = key
  if (key === 'cases') loadCases()
  if (key === 'conflicts') loadConflicts()
  if (key === 'batch') loadSimulations()
}

watch(
  () => props.rulesetId,
  () => {
    singleResult.value = null
    batchResult.value = null
    caseResult.value = null
    runAllResult.value = null
    detectNotice.value = ''
    cases.value = []
    conflicts.value = []
    simulations.value = []
    if (panel.value === 'cases') loadCases()
    if (panel.value === 'conflicts') loadConflicts()
    if (panel.value === 'batch') loadSimulations()
  }
)

watch(
  () => props.refreshKey,
  () => {
    if (panel.value === 'cases') loadCases()
    if (panel.value === 'conflicts') loadConflicts()
    if (panel.value === 'batch') loadSimulations()
  }
)

onMounted(() => {
  if (props.rulesetId) loadSimulations()
})
</script>