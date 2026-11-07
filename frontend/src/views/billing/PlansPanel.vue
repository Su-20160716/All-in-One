<template>
  <section class="space-y-3">
    <!-- 内部分区 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <div class="flex flex-wrap gap-1">
        <button
          v-for="s in SUB_TABS"
          :key="s.key"
          type="button"
          class="rounded-pill px-3 py-1 text-[12px] transition-colors"
          :class="subTab === s.key ? 'bg-brand-600 text-white' : 'border border-ink-200 bg-white text-ink-600 hover:border-brand-300'"
          @click="switchSubTab(s.key)"
        >{{ s.label }}</button>
      </div>
      <span class="ml-auto text-[11px] text-ink-400">
        套餐、价格、功能包含量、优惠券与税率全部落库，修改后立即影响后续订阅与账单
      </span>
    </div>

    <!-- 计划与价格 -->
    <template v-if="subTab === 'plans'">
      <div class="card flex flex-wrap items-end gap-2 p-3">
        <label class="min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input v-model="planQ" class="input" type="search" placeholder="按编码、名称或描述搜索" @keyup.enter="searchPlans" />
        </label>
        <label class="w-32">
          <span class="mb-1 block text-[11px] text-ink-400">状态</span>
          <select v-model="planStatus" class="input" @change="searchPlans">
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="active">已发布</option>
            <option value="archived">已停用</option>
          </select>
        </label>
        <label class="w-32">
          <span class="mb-1 block text-[11px] text-ink-400">计费周期</span>
          <select v-model="planPeriod" class="input" @change="searchPlans">
            <option value="">全部周期</option>
            <option value="monthly">按月</option>
            <option value="yearly">按年</option>
            <option value="one_time">一次性</option>
          </select>
        </label>
        <label class="w-24">
          <span class="mb-1 block text-[11px] text-ink-400">每页</span>
          <select class="input" :value="planPageSize" @change="changePlanPageSize($event)">
            <option v-for="n in [10, 20, 50]" :key="n" :value="n">{{ n }} 条</option>
          </select>
        </label>
        <button class="btn-primary" @click="searchPlans">查询</button>
        <button class="btn-ghost" :disabled="planLoading" @click="loadPlans">刷新</button>
        <span class="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
          <span>共 {{ formatNumber(planCount) }} 个套餐</span>
          <button class="btn-primary px-3 py-1 text-[12px]" @click="openPlan()">新建套餐</button>
        </span>
      </div>

      <div class="card overflow-hidden">
        <div v-if="planLoading && !plans.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="planError" class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ planError }}</span>
          <button class="font-medium" @click="loadPlans">重试</button>
        </div>
        <div v-else-if="planUnavailable && !plans.length" class="py-12 text-center text-[12px] text-amber-700">
          {{ planUnavailable }}。套餐端点恢复后重新刷新即可加载。
        </div>
        <div v-else-if="!plans.length" class="py-12 text-center text-[12px] text-ink-400">
          {{ planQ || planStatus || planPeriod ? '没有匹配的套餐，调整筛选条件后重试' : '还没有套餐，先新建一个草稿并配置价格' }}
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[1040px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">套餐</th>
                <th class="th">状态</th>
                <th class="th">周期</th>
                <th class="th">试用</th>
                <th class="th">价格</th>
                <th class="th">排序</th>
                <th class="th">更新时间</th>
                <th class="th">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in plans" :key="row.id" class="cursor-pointer hover:bg-ink-50/50" @click="openDetail(row)">
                <td class="td">
                  <div class="max-w-[260px]">
                    <div class="truncate font-medium text-ink-800">{{ row.name }}</div>
                    <div class="truncate font-mono text-[11px] text-ink-400">{{ row.code }}</div>
                  </div>
                </td>
                <td class="td">
                  <span class="tag" :class="tagClass(statusTone(row.status))">{{ row.status_label || planStatusLabel(row.status) }}</span>
                </td>
                <td class="td text-[12px] text-ink-500">{{ row.billing_period_label || row.billing_period }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.trial_days || 0 }} 天</td>
                <td class="td text-[12px]">{{ priceSummary(row) }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.sort_order }}</td>
                <td class="td text-[12px] text-ink-500">{{ formatDate(row.updated_at, true) }}</td>
                <td class="td whitespace-nowrap" @click.stop>
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openDetail(row)">详情</button>
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openPlan(row)">编辑</button>
                  <button
                    v-if="row.status !== 'active'"
                    class="btn-ghost px-1.5 text-[12px] text-brand-600"
                    :disabled="busyPlanId === row.id"
                    @click="planAction(row, 'publish')"
                  >发布</button>
                  <button
                    v-else
                    class="btn-ghost px-1.5 text-[12px] text-amber-600"
                    :disabled="busyPlanId === row.id"
                    @click="planAction(row, 'archive')"
                  >停用</button>
                  <button class="btn-ghost px-1.5 text-[12px]" :disabled="busyPlanId === row.id" @click="planAction(row, 'clone')">克隆</button>
                  <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="askDelete('plan', row)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
          <span>第 {{ planPage }} / {{ planPages }} 页 · 每页 {{ planPageSize }} 条</span>
          <span class="flex items-center gap-1">
            <button class="btn-ghost px-2 text-[12px]" :disabled="planPage <= 1 || planLoading" @click="gotoPlanPage(planPage - 1)">上一页</button>
            <button
              v-for="p in planPageButtons"
              :key="p"
              class="rounded-control px-2 py-0.5 text-[12px]"
              :class="p === planPage ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-100'"
              @click="gotoPlanPage(p)"
            >{{ p }}</button>
            <button class="btn-ghost px-2 text-[12px]" :disabled="planPage >= planPages || planLoading" @click="gotoPlanPage(planPage + 1)">下一页</button>
          </span>
        </div>
      </div>
    </template>

    <!-- 功能项 -->
    <template v-else-if="subTab === 'features'">
      <div class="card flex flex-wrap items-end gap-2 p-3">
        <label class="min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input v-model="featureQ" class="input" type="search" placeholder="按功能编码、名称或描述搜索" @keyup.enter="searchFeatures" />
        </label>
        <label class="w-32">
          <span class="mb-1 block text-[11px] text-ink-400">状态</span>
          <select v-model="featureStatus" class="input" @change="searchFeatures">
            <option value="">全部状态</option>
            <option value="active">启用</option>
            <option value="archived">停用</option>
          </select>
        </label>
        <button class="btn-primary" @click="searchFeatures">查询</button>
        <button class="btn-ghost" :disabled="featureLoading" @click="loadFeatures">刷新</button>
        <span class="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
          <span>共 {{ formatNumber(featureCount) }} 项</span>
          <button class="btn-primary px-3 py-1 text-[12px]" @click="openFeature()">新建功能项</button>
        </span>
      </div>

      <div class="card overflow-hidden">
        <div v-if="featureLoading && !features.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="featureError" class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ featureError }}</span>
          <button class="font-medium" @click="loadFeatures">重试</button>
        </div>
        <div v-else-if="!features.length" class="py-12 text-center text-[12px] text-ink-400">
          还没有功能项，先定义可被套餐包含的开关、配额或计量能力
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[900px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">编码 / 名称</th>
                <th class="th">类型</th>
                <th class="th">单位</th>
                <th class="th">状态</th>
                <th class="th">说明</th>
                <th class="th">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in features" :key="row.id" class="hover:bg-ink-50/50">
                <td class="td">
                  <div class="font-mono text-[12px] text-ink-700">{{ row.code }}</div>
                  <div class="text-[11px] text-ink-400">{{ row.name }}</div>
                </td>
                <td class="td text-[12px] text-ink-500">{{ row.feature_type_label || row.feature_type }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.unit || '—' }}</td>
                <td class="td">
                  <span class="tag" :class="row.status === 'active' ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                    {{ row.status === 'active' ? '启用' : '停用' }}
                  </span>
                </td>
                <td class="td max-w-[220px] truncate text-[12px] text-ink-500">{{ row.description || '—' }}</td>
                <td class="td whitespace-nowrap">
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openFeature(row)">编辑</button>
                  <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="askDelete('feature', row)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
          <span>第 {{ featurePage }} / {{ featurePages }} 页 · 每页 {{ featurePageSize }} 条</span>
          <span class="flex items-center gap-1">
            <button class="btn-ghost px-2 text-[12px]" :disabled="featurePage <= 1" @click="gotoFeaturePage(featurePage - 1)">上一页</button>
            <span>第 {{ featurePage }} 页</span>
            <button class="btn-ghost px-2 text-[12px]" :disabled="featurePage >= featurePages" @click="gotoFeaturePage(featurePage + 1)">下一页</button>
          </span>
        </div>
      </div>
    </template>

    <!-- 优惠券 -->
    <template v-else-if="subTab === 'coupons'">
      <div class="card flex flex-wrap items-end gap-2 p-3">
        <label class="min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input v-model="couponQ" class="input" type="search" placeholder="按优惠码、名称或描述搜索" @keyup.enter="searchCoupons" />
        </label>
        <label class="w-32">
          <span class="mb-1 block text-[11px] text-ink-400">状态</span>
          <select v-model="couponStatus" class="input" @change="searchCoupons">
            <option value="">全部状态</option>
            <option value="active">可用</option>
            <option value="archived">已停用</option>
          </select>
        </label>
        <button class="btn-primary" @click="searchCoupons">查询</button>
        <button class="btn-ghost" :disabled="couponLoading" @click="loadCoupons">刷新</button>
        <span class="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
          <span>共 {{ formatNumber(couponCount) }} 张</span>
          <button class="btn-primary px-3 py-1 text-[12px]" @click="openCoupon()">新建优惠券</button>
        </span>
      </div>

      <div class="card overflow-hidden">
        <div v-if="couponLoading && !coupons.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="couponError" class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ couponError }}</span>
          <button class="font-medium" @click="loadCoupons">重试</button>
        </div>
        <div v-else-if="couponUnavailable && !coupons.length" class="py-12 text-center text-[12px] text-amber-700">
          {{ couponUnavailable }}。优惠券端点恢复后重新刷新即可加载。
        </div>
        <div v-else-if="!coupons.length" class="py-12 text-center text-[12px] text-ink-400">
          还没有优惠券，新建一张百分比或固定金额券用于账单抵扣
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[1000px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">优惠码 / 名称</th>
                <th class="th">类型</th>
                <th class="th">优惠力度</th>
                <th class="th">持续时间</th>
                <th class="th">核销</th>
                <th class="th">有效期</th>
                <th class="th">状态</th>
                <th class="th">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in coupons" :key="row.id" class="hover:bg-ink-50/50">
                <td class="td">
                  <div class="font-mono text-[12px] text-ink-700">{{ row.code }}</div>
                  <div class="text-[11px] text-ink-400">{{ row.name }}</div>
                </td>
                <td class="td text-[12px] text-ink-500">{{ row.coupon_type_label || row.coupon_type }}</td>
                <td class="td text-[12px]">{{ couponDiscount(row) }}</td>
                <td class="td text-[12px] text-ink-500">{{ couponDuration(row) }}</td>
                <td class="td text-[12px]">
                  {{ row.redeemed_count || 0 }} / {{ row.max_redemptions || '不限' }}
                </td>
                <td class="td text-[11px] text-ink-500">{{ couponValidity(row) }}</td>
                <td class="td">
                  <span class="tag" :class="row.status === 'active' ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                    {{ row.status_label || (row.status === 'active' ? '可用' : '已停用') }}
                  </span>
                </td>
                <td class="td whitespace-nowrap">
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openCoupon(row)">编辑</button>
                  <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="askDelete('coupon', row)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
          <span>第 {{ couponPage }} / {{ couponPages }} 页 · 每页 {{ couponPageSize }} 条</span>
          <span class="flex items-center gap-1">
            <button class="btn-ghost px-2 text-[12px]" :disabled="couponPage <= 1" @click="gotoCouponPage(couponPage - 1)">上一页</button>
            <span>第 {{ couponPage }} 页</span>
            <button class="btn-ghost px-2 text-[12px]" :disabled="couponPage >= couponPages" @click="gotoCouponPage(couponPage + 1)">下一页</button>
          </span>
        </div>
      </div>
    </template>

    <!-- 税率 -->
    <template v-else>
      <div class="card flex flex-wrap items-end gap-2 p-3">
        <label class="min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input v-model="taxQ" class="input" type="search" placeholder="按名称、国家或地区搜索" @keyup.enter="searchTaxes" />
        </label>
        <label class="w-32">
          <span class="mb-1 block text-[11px] text-ink-400">启用状态</span>
          <select v-model="taxEnabled" class="input" @change="searchTaxes">
            <option value="">全部</option>
            <option value="true">启用</option>
            <option value="false">停用</option>
          </select>
        </label>
        <button class="btn-primary" @click="searchTaxes">查询</button>
        <button class="btn-ghost" :disabled="taxLoading" @click="loadTaxes">刷新</button>
        <span class="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
          <span>共 {{ formatNumber(taxCount) }} 条</span>
          <button class="btn-primary px-3 py-1 text-[12px]" @click="openTax()">新建税率</button>
        </span>
      </div>

      <div class="card overflow-hidden">
        <div v-if="taxLoading && !taxes.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="taxError" class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ taxError }}</span>
          <button class="font-medium" @click="loadTaxes">重试</button>
        </div>
        <div v-else-if="taxUnavailable && !taxes.length" class="py-12 text-center text-[12px] text-amber-700">
          {{ taxUnavailable }}。税率端点恢复后重新刷新即可加载。
        </div>
        <div v-else-if="!taxes.length" class="py-12 text-center text-[12px] text-ink-400">
          还没有税率，新建一条国家/地区税率后生成账单会自动计税
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[880px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">国家 / 地区</th>
                <th class="th">税种名称</th>
                <th class="th">税率</th>
                <th class="th">生效区间</th>
                <th class="th">启用</th>
                <th class="th">默认</th>
                <th class="th">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in taxes" :key="row.id" class="hover:bg-ink-50/50">
                <td class="td text-[12px]">{{ row.country }} <span class="text-ink-400">{{ row.region || '全部地区' }}</span></td>
                <td class="td text-[12px]">{{ row.name }}</td>
                <td class="td text-[12px] font-medium">{{ row.rate }}%</td>
                <td class="td text-[11px] text-ink-500">
                  {{ row.effective_from || '不限' }} ~ {{ row.effective_to || '不限' }}
                </td>
                <td class="td">
                  <span class="tag" :class="row.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                    {{ row.enabled ? '启用' : '停用' }}
                  </span>
                </td>
                <td class="td">
                  <span v-if="row.is_default" class="tag bg-brand-50 text-brand-700">默认</span>
                  <span v-else class="text-[11px] text-ink-400">—</span>
                </td>
                <td class="td whitespace-nowrap">
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openTax(row)">编辑</button>
                  <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="askDelete('tax', row)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
          <span>第 {{ taxPage }} / {{ taxPages }} 页 · 每页 {{ taxPageSize }} 条</span>
          <span class="flex items-center gap-1">
            <button class="btn-ghost px-2 text-[12px]" :disabled="taxPage <= 1" @click="gotoTaxPage(taxPage - 1)">上一页</button>
            <span>第 {{ taxPage }} 页</span>
            <button class="btn-ghost px-2 text-[12px]" :disabled="taxPage >= taxPages" @click="gotoTaxPage(taxPage + 1)">下一页</button>
          </span>
        </div>
      </div>
    </template>

    <!-- 套餐新建 / 编辑 -->
    <Modal :show="planModalOpen" :title="planForm.id ? '编辑套餐' : '新建套餐'" width="640px" @close="closePlan">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">套餐编码</span>
            <input v-model="planForm.code" class="input" maxlength="60" placeholder="如 pro_monthly" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">套餐名称</span>
            <input v-model="planForm.name" class="input" maxlength="120" placeholder="如 专业版" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">计费周期</span>
            <select v-model="planForm.billing_period" class="input">
              <option value="monthly">按月</option>
              <option value="yearly">按年</option>
              <option value="one_time">一次性</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">试用天数</span>
            <input v-model.number="planForm.trial_days" class="input" type="number" min="0" max="365" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">状态</span>
            <select v-model="planForm.status" class="input">
              <option value="draft">草稿</option>
              <option value="active">已发布</option>
              <option value="archived">已停用</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">排序</span>
            <input v-model.number="planForm.sort_order" class="input" type="number" min="-100000" max="100000" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">描述</span>
          <textarea v-model="planForm.description" class="input min-h-[64px]" maxlength="5000" placeholder="套餐面向的客户与权益说明" />
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">功能上限（JSON 对象，可选）</span>
          <textarea v-model="planForm.limitsText" class="input min-h-[80px] font-mono text-[11px]" placeholder='{"projects": 20, "seats": 10}' />
        </label>
        <p class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          发布前必须至少有一条生效价格；发布后即可在订阅页开通，停用不影响已有订阅继续计费。
        </p>
        <div v-if="planFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ planFormError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closePlan">取消</button>
          <button class="btn-primary" :disabled="planSaving" @click="savePlan">
            {{ planSaving ? '保存中…' : '保存套餐' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 套餐详情抽屉 -->
    <div v-if="detailOpen" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDetail"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[680px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="tagClass(statusTone(detail?.status))">
                {{ detail?.status_label || planStatusLabel(detail?.status) }}
              </span>
              <span class="tag">{{ detail?.billing_period_label || detail?.billing_period || '—' }}</span>
              <span class="tag">试用 {{ detail?.trial_days || 0 }} 天</span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">{{ detail?.name || '套餐详情' }}</h3>
            <p class="truncate font-mono text-[11px] text-ink-400">{{ detail?.code || '' }}</p>
          </div>
          <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" @click="closeDetail">✕</button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <div v-if="detailLoading" class="py-10 text-center text-[12px] text-ink-400">详情加载中…</div>
          <div v-else-if="detailError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <div class="truncate">{{ detailError }}</div>
            <button class="mt-1 font-medium" @click="loadDetail(detailId)">重试</button>
          </div>
          <template v-else-if="detail">
            <div class="grid grid-cols-2 gap-2 text-[12px] sm:grid-cols-4">
              <div class="rounded-control bg-ink-50 px-3 py-2">
                <div class="text-[11px] text-ink-400">订阅总数</div>
                <div class="mt-0.5 text-[16px] font-semibold text-ink-800">{{ formatNumber(detail.stats?.subscriptions) }}</div>
              </div>
              <div class="rounded-control bg-emerald-50 px-3 py-2">
                <div class="text-[11px] text-emerald-600">在服订阅</div>
                <div class="mt-0.5 text-[16px] font-semibold text-emerald-700">{{ formatNumber(detail.stats?.active_subscriptions) }}</div>
              </div>
              <div class="rounded-control bg-brand-50 px-3 py-2">
                <div class="text-[11px] text-brand-600">MRR</div>
                <div class="mt-0.5 text-[16px] font-semibold text-brand-700">{{ formatMoney(detail.stats?.mrr) }}</div>
              </div>
              <div class="rounded-control bg-ink-50 px-3 py-2">
                <div class="text-[11px] text-ink-400">价格 / 功能</div>
                <div class="mt-0.5 text-[16px] font-semibold text-ink-800">
                  {{ (detail.prices || []).length }} / {{ (detail.plan_features || []).length }}
                </div>
              </div>
            </div>

            <p v-if="detail.description" class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
              {{ detail.description }}
            </p>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">价格</span>
                <button class="btn-outline px-2 py-0.5 text-[12px]" @click="openPrice()">新增价格</button>
              </div>
              <div v-if="!(detail.prices || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                还没有价格，发布套餐前至少需要一条生效价格
              </div>
              <div v-else class="overflow-x-auto rounded-control border border-ink-100">
                <table class="w-full min-w-[600px]">
                  <thead class="bg-ink-50/60">
                    <tr>
                      <th class="th">币种</th>
                      <th class="th">金额</th>
                      <th class="th">模式</th>
                      <th class="th">别名</th>
                      <th class="th">生效区间</th>
                      <th class="th">状态</th>
                      <th class="th">操作</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-ink-50">
                    <tr v-for="price in detail.prices" :key="price.id">
                      <td class="td text-[12px]">{{ price.currency }}</td>
                      <td class="td text-[12px]">{{ price.amount }}</td>
                      <td class="td text-[12px] text-ink-500">{{ price.billing_mode_label || price.billing_mode }}</td>
                      <td class="td max-w-[120px] truncate text-[12px] text-ink-500">{{ price.nickname || '—' }}</td>
                      <td class="td text-[11px] text-ink-500">{{ price.effective_from || '不限' }} ~ {{ price.effective_to || '不限' }}</td>
                      <td class="td">
                        <span class="tag" :class="price.status === 'active' ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                          {{ price.status === 'active' ? '生效' : '停用' }}
                        </span>
                      </td>
                      <td class="td whitespace-nowrap">
                        <button class="btn-ghost px-1 text-[12px]" @click="openPrice(price)">编辑</button>
                        <button class="btn-ghost px-1 text-[12px] text-rose-500" @click="askDelete('price', price)">删除</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">功能包含量与超量单价</span>
                <button class="btn-outline px-2 py-0.5 text-[12px]" @click="openBinding()">绑定功能</button>
              </div>
              <div v-if="!(detail.plan_features || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                还没有绑定功能，绑定后可配置包含量与超量单价
              </div>
              <div v-else class="overflow-x-auto rounded-control border border-ink-100">
                <table class="w-full min-w-[620px]">
                  <thead class="bg-ink-50/60">
                    <tr>
                      <th class="th">功能</th>
                      <th class="th">类型</th>
                      <th class="th">包含量</th>
                      <th class="th">单位</th>
                      <th class="th">超量单价</th>
                      <th class="th">操作</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-ink-50">
                    <tr v-for="binding in detail.plan_features" :key="binding.id">
                      <td class="td text-[12px]">
                        {{ binding.feature_name }}
                        <span class="font-mono text-[11px] text-ink-400">{{ binding.feature_code }}</span>
                      </td>
                      <td class="td text-[12px] text-ink-500">{{ binding.feature_type }}</td>
                      <td class="td text-[12px]">{{ binding.included_qty }}</td>
                      <td class="td text-[12px] text-ink-500">{{ binding.unit || '—' }}</td>
                      <td class="td text-[12px]">{{ binding.overage_unit_amount }}</td>
                      <td class="td whitespace-nowrap">
                        <button class="btn-ghost px-1 text-[12px]" @click="openBinding(binding)">编辑</button>
                        <button class="btn-ghost px-1 text-[12px] text-rose-500" @click="askDelete('binding', binding)">解绑</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">套餐事件</span>
                <span class="tag">{{ (detail.events || []).length }} 条</span>
              </div>
              <div v-if="!(detail.events || []).length" class="rounded-control bg-ink-50 px-3 py-3 text-center text-[12px] text-ink-400">
                暂无事件
              </div>
              <ul v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <li v-for="ev in detail.events" :key="ev.id" class="flex items-center gap-2 px-3 py-1.5 text-[12px]">
                  <span class="min-w-0 flex-1 truncate text-ink-700">{{ ev.event_type }}</span>
                  <span class="shrink-0 text-[11px] text-ink-400">{{ formatDate(ev.created_at, true) }}</span>
                </li>
              </ul>
            </div>

            <div>
              <div class="mb-1 text-[13px] font-medium text-ink-700">功能上限</div>
              <pre class="max-h-32 overflow-auto rounded-control bg-ink-50 px-3 py-2 font-mono text-[11px] text-ink-600">{{ limitsText }}</pre>
            </div>
          </template>
        </div>

        <div class="flex flex-wrap items-center gap-2 border-t border-ink-100 px-4 py-2.5">
          <button
            v-if="detail?.status !== 'active'"
            class="btn-primary px-3 py-1 text-[12px]"
            :disabled="busyPlanId === detail?.id"
            @click="planAction(detail, 'publish')"
          >发布套餐</button>
          <button
            v-else
            class="btn-outline px-3 py-1 text-[12px]"
            :disabled="busyPlanId === detail?.id"
            @click="planAction(detail, 'archive')"
          >停用套餐</button>
          <button class="btn-outline px-3 py-1 text-[12px]" :disabled="busyPlanId === detail?.id" @click="planAction(detail, 'clone')">
            克隆套餐
          </button>
          <button class="btn-ghost px-3 py-1 text-[12px]" @click="openPlan(detail)">编辑套餐</button>
          <button class="btn-danger ml-auto px-3 py-1 text-[12px]" @click="askDelete('plan', detail)">删除套餐</button>
        </div>
      </aside>
    </div>

    <!-- 价格新建 / 编辑 -->
    <Modal :show="priceModalOpen" :title="priceForm.id ? '编辑价格' : '新增价格'" width="600px" @close="closePrice">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">币种</span>
            <input v-model="priceForm.currency" class="input" maxlength="8" placeholder="CNY / USD" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">计费模式</span>
            <select v-model="priceForm.billing_mode" class="input">
              <option value="flat">固定价</option>
              <option value="per_unit">按量</option>
              <option value="tiered">阶梯</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">金额 / 单价</span>
            <input v-model="priceForm.amount" class="input" inputmode="decimal" placeholder="保留 4 位小数" :disabled="priceForm.billing_mode === 'tiered'" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">别名</span>
            <input v-model="priceForm.nickname" class="input" maxlength="120" placeholder="如 标准月付" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">生效起始</span>
            <input v-model="priceForm.effective_from" class="input" type="date" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">生效截止</span>
            <input v-model="priceForm.effective_to" class="input" type="date" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">状态</span>
            <select v-model="priceForm.status" class="input">
              <option value="active">生效</option>
              <option value="archived">停用</option>
            </select>
          </label>
        </div>
        <label v-if="priceForm.billing_mode === 'tiered'" class="block text-[12px] text-ink-600">
          <span class="mb-1 block">阶梯配置（JSON 数组）</span>
          <textarea
            v-model="priceForm.tiersText"
            class="input min-h-[90px] font-mono text-[11px]"
            placeholder='[{"up_to": 100, "unit_amount": 0.5}, {"up_to": null, "unit_amount": 0.3}]'
          />
        </label>
        <div v-if="priceFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ priceFormError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closePrice">取消</button>
          <button class="btn-primary" :disabled="priceSaving" @click="savePrice">
            {{ priceSaving ? '保存中…' : '保存价格' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 计划功能绑定 -->
    <Modal :show="bindingModalOpen" :title="bindingForm.id ? '编辑功能包含量' : '绑定功能'" width="560px" @close="closeBinding">
      <div class="space-y-3">
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">功能项</span>
          <select v-model="bindingForm.feature_id" class="input" :disabled="Boolean(bindingForm.id)">
            <option value="">请选择功能项</option>
            <option v-for="f in featureOptions" :key="f.id" :value="f.id">{{ f.name }}（{{ f.code }}）</option>
          </select>
        </label>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">包含量</span>
            <input v-model="bindingForm.included_qty" class="input" inputmode="decimal" placeholder="0 表示不包含" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">单位</span>
            <input v-model="bindingForm.unit" class="input" maxlength="20" placeholder="次 / GB" />
          </label>
          <label class="block text-[12px] text-ink-600 sm:col-span-2">
            <span class="mb-1 block">超量单价</span>
            <input v-model="bindingForm.overage_unit_amount" class="input" inputmode="decimal" placeholder="超出包含量后每单位价格" />
          </label>
        </div>
        <p class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          账单中的超量金额 = max(用量 - 包含量, 0) × 超量单价；包含量固定写入发票行项快照。
        </p>
        <div v-if="bindingError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ bindingError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeBinding">取消</button>
          <button class="btn-primary" :disabled="bindingSaving" @click="saveBinding">
            {{ bindingSaving ? '保存中…' : '保存绑定' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 功能项新建 / 编辑 -->
    <Modal :show="featureModalOpen" :title="featureForm.id ? '编辑功能项' : '新建功能项'" width="560px" @close="closeFeature">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">功能编码</span>
            <input v-model="featureForm.code" class="input" maxlength="60" placeholder="如 api.calls" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">功能名称</span>
            <input v-model="featureForm.name" class="input" maxlength="120" placeholder="如 API 调用" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">功能类型</span>
            <select v-model="featureForm.feature_type" class="input">
              <option value="boolean">开关</option>
              <option value="quota">配额</option>
              <option value="metered">计量</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">单位</span>
            <input v-model="featureForm.unit" class="input" maxlength="20" placeholder="次 / GB / 席位" />
          </label>
          <label class="block text-[12px] text-ink-600 sm:col-span-2">
            <span class="mb-1 block">状态</span>
            <select v-model="featureForm.status" class="input">
              <option value="active">启用</option>
              <option value="archived">停用</option>
            </select>
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">说明</span>
          <textarea v-model="featureForm.description" class="input min-h-[64px]" maxlength="5000" placeholder="描述该功能对客户的价值" />
        </label>
        <div v-if="featureFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ featureFormError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeFeature">取消</button>
          <button class="btn-primary" :disabled="featureSaving" @click="saveFeature">
            {{ featureSaving ? '保存中…' : '保存功能项' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 优惠券新建 / 编辑 -->
    <Modal :show="couponModalOpen" :title="couponForm.id ? '编辑优惠券' : '新建优惠券'" width="640px" @close="closeCoupon">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">优惠码</span>
            <input v-model="couponForm.code" class="input font-mono" maxlength="60" placeholder="如 SAVE20" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">名称</span>
            <input v-model="couponForm.name" class="input" maxlength="120" placeholder="如 新客八折" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">类型</span>
            <select v-model="couponForm.coupon_type" class="input">
              <option value="percent">百分比</option>
              <option value="fixed">固定金额</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">{{ couponForm.coupon_type === 'percent' ? '折扣百分比' : '固定减免金额' }}</span>
            <input
              v-if="couponForm.coupon_type === 'percent'"
              v-model="couponForm.percent"
              class="input"
              inputmode="decimal"
              placeholder="如 20 表示八折"
            />
            <input v-else v-model="couponForm.amount" class="input" inputmode="decimal" placeholder="如 50" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">币种</span>
            <input v-model="couponForm.currency" class="input" maxlength="8" placeholder="CNY" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">持续时间</span>
            <select v-model="couponForm.duration" class="input">
              <option value="once">仅一次</option>
              <option value="repeating">重复 N 期</option>
              <option value="forever">永久</option>
            </select>
          </label>
          <label v-if="couponForm.duration === 'repeating'" class="block text-[12px] text-ink-600">
            <span class="mb-1 block">重复期数</span>
            <input v-model.number="couponForm.duration_months" class="input" type="number" min="1" max="120" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">最大核销次数</span>
            <input v-model.number="couponForm.max_redemptions" class="input" type="number" min="0" max="1000000" placeholder="0 表示不限" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">生效时间</span>
            <input v-model="couponForm.valid_from" class="input" type="datetime-local" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">失效时间</span>
            <input v-model="couponForm.valid_until" class="input" type="datetime-local" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">状态</span>
            <select v-model="couponForm.status" class="input">
              <option value="active">可用</option>
              <option value="archived">已停用</option>
            </select>
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">说明</span>
          <textarea v-model="couponForm.description" class="input min-h-[56px]" maxlength="5000" />
        </label>
        <div v-if="couponFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ couponFormError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeCoupon">取消</button>
          <button class="btn-primary" :disabled="couponSaving" @click="saveCoupon">
            {{ couponSaving ? '保存中…' : '保存优惠券' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 税率新建 / 编辑 -->
    <Modal :show="taxModalOpen" :title="taxForm.id ? '编辑税率' : '新建税率'" width="580px" @close="closeTax">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">国家 / 地区代码</span>
            <input v-model="taxForm.country" class="input" maxlength="8" placeholder="CN" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">省 / 州（可选）</span>
            <input v-model="taxForm.region" class="input" maxlength="60" placeholder="如 上海" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">税种名称</span>
            <input v-model="taxForm.name" class="input" maxlength="120" placeholder="增值税" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">税率（%）</span>
            <input v-model="taxForm.rate" class="input" inputmode="decimal" placeholder="0 - 100" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">生效起始</span>
            <input v-model="taxForm.effective_from" class="input" type="date" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">生效截止</span>
            <input v-model="taxForm.effective_to" class="input" type="date" />
          </label>
        </div>
        <div class="flex flex-wrap gap-4 text-[12px] text-ink-600">
          <label class="flex items-center gap-1"><input v-model="taxForm.enabled" type="checkbox" /> 启用</label>
          <label class="flex items-center gap-1"><input v-model="taxForm.is_default" type="checkbox" /> 设为该国家默认税率</label>
        </div>
        <div v-if="taxFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ taxFormError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeTax">取消</button>
          <button class="btn-primary" :disabled="taxSaving" @click="saveTax">
            {{ taxSaving ? '保存中…' : '保存税率' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 通用删除确认 -->
    <Modal :show="confirmOpen" :title="confirmMeta.title" width="460px" @close="closeConfirm">
      <div class="space-y-3 text-[12px]">
        <p class="text-ink-600">{{ confirmMeta.description }}</p>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-ink-600">
          {{ confirmTargetLabel }}
        </div>
        <div v-if="confirmError" class="rounded-control bg-rose-50 px-3 py-2 text-rose-600">{{ confirmError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeConfirm">取消</button>
          <button class="btn-danger" :disabled="confirmBusy" @click="submitConfirm">
            {{ confirmBusy ? '处理中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { billingApi } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
  statusTone,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])
const app = useAppStore()

const SUB_TABS = [
  { key: 'plans', label: '计划与价格' },
  { key: 'features', label: '功能项' },
  { key: 'coupons', label: '优惠券' },
  { key: 'tax', label: '税率' },
]

const subTab = ref('plans')

const plans = ref([])
const planCount = ref(0)
const planPage = ref(1)
const planPageSize = ref(20)
const planQ = ref('')
const planStatus = ref('')
const planPeriod = ref('')
const planLoading = ref(false)
const planError = ref('')
const planUnavailable = ref('')
const busyPlanId = ref(null)

const planModalOpen = ref(false)
const planForm = ref(defaultPlanForm())
const planFormError = ref('')
const planSaving = ref(false)

const detailOpen = ref(false)
const detailId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const priceModalOpen = ref(false)
const priceForm = ref(defaultPriceForm())
const priceFormError = ref('')
const priceSaving = ref(false)

const bindingModalOpen = ref(false)
const bindingForm = ref(defaultBindingForm())
const bindingError = ref('')
const bindingSaving = ref(false)

const features = ref([])
const featureCount = ref(0)
const featurePage = ref(1)
const featurePageSize = ref(20)
const featureQ = ref('')
const featureStatus = ref('')
const featureLoading = ref(false)
const featureError = ref('')
const featureModalOpen = ref(false)
const featureForm = ref(defaultFeatureForm())
const featureFormError = ref('')
const featureSaving = ref(false)
const featureOptions = ref([])

const coupons = ref([])
const couponCount = ref(0)
const couponPage = ref(1)
const couponPageSize = ref(20)
const couponQ = ref('')
const couponStatus = ref('')
const couponLoading = ref(false)
const couponError = ref('')
const couponUnavailable = ref('')
const couponModalOpen = ref(false)
const couponForm = ref(defaultCouponForm())
const couponFormError = ref('')
const couponSaving = ref(false)

const taxes = ref([])
const taxCount = ref(0)
const taxPage = ref(1)
const taxPageSize = ref(20)
const taxQ = ref('')
const taxEnabled = ref('')
const taxLoading = ref(false)
const taxError = ref('')
const taxUnavailable = ref('')
const taxModalOpen = ref(false)
const taxForm = ref(defaultTaxForm())
const taxFormError = ref('')
const taxSaving = ref(false)

const confirmOpen = ref(false)
const confirmKind = ref('')
const confirmRow = ref(null)
const confirmBusy = ref(false)
const confirmError = ref('')

const CONFIRM_META = {
  plan: {
    title: '删除套餐',
    description: '删除后不可恢复；存在订阅的套餐会被后端拒绝删除，请先停用。',
  },
  price: {
    title: '删除价格',
    description: '已被订阅明细引用的价格不能删除，请改为停用。',
  },
  binding: {
    title: '解绑功能',
    description: '解绑后该功能不再计入此套餐的包含量与超量单价。',
  },
  feature: {
    title: '删除功能项',
    description: '已绑定到套餐的功能不能删除，请先解绑或停用。',
  },
  coupon: {
    title: '删除优惠券',
    description: '已有核销记录的优惠券不能删除，请改为停用。',
  },
  tax: {
    title: '删除税率',
    description: '历史发票行项已固化税率快照，删除不会影响旧账单。',
  },
}

const planPages = computed(() => Math.max(1, Math.ceil(planCount.value / Math.max(1, planPageSize.value))))
const planPageButtons = computed(() => {
  const total = planPages.value
  const start = Math.max(1, Math.min(planPage.value - 2, total - 4))
  const end = Math.min(total, start + 4)
  const out = []
  for (let i = start; i <= end; i += 1) out.push(i)
  return out
})
const featurePages = computed(() => Math.max(1, Math.ceil(featureCount.value / Math.max(1, featurePageSize.value))))
const couponPages = computed(() => Math.max(1, Math.ceil(couponCount.value / Math.max(1, couponPageSize.value))))
const taxPages = computed(() => Math.max(1, Math.ceil(taxCount.value / Math.max(1, taxPageSize.value))))

const confirmMeta = computed(() => CONFIRM_META[confirmKind.value] || {
  title: '确认删除',
  description: '删除后不可恢复。',
})

const confirmTargetLabel = computed(() => {
  const row = confirmRow.value
  if (!row) return '—'
  if (confirmKind.value === 'plan') return `${row.name}（${row.code}）`
  if (confirmKind.value === 'price') return `${row.currency} ${row.amount} · ${row.billing_mode}`
  if (confirmKind.value === 'binding') return `${row.feature_name}（${row.feature_code}）`
  if (confirmKind.value === 'feature') return `${row.name}（${row.code}）`
  if (confirmKind.value === 'coupon') return `${row.name}（${row.code}）`
  if (confirmKind.value === 'tax') return `${row.country} ${row.region || ''} · ${row.name} ${row.rate}%`
  return '—'
})

const limitsText = computed(() => {
  const limits = detail.value?.limits || {}
  return JSON.stringify(limits, null, 2)
})

function planStatusLabel(value) {
  return { draft: '草稿', active: '已发布', archived: '已停用' }[value] || value || '未知'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function isUnavailable(e) {
  const code = Number(e?.status || e?.response?.status || 0)
  return code === 404 || code === 405
}

function isoText(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toISOString()
}

function parseObject(text, label) {
  const value = String(text || '').trim()
  if (!value) return {}
  const parsed = JSON.parse(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 对象`)
  }
  return parsed
}

function parseArray(text, label) {
  const value = String(text || '').trim()
  if (!value) return []
  const parsed = JSON.parse(value)
  if (!Array.isArray(parsed)) throw new Error(`${label}必须是 JSON 数组`)
  return parsed
}

function defaultPlanForm() {
  return {
    id: null,
    code: '',
    name: '',
    description: '',
    billing_period: 'monthly',
    trial_days: 0,
    sort_order: 0,
    status: 'draft',
    limitsText: '{}',
  }
}

function defaultPriceForm() {
  return {
    id: null,
    currency: 'CNY',
    amount: '',
    billing_mode: 'flat',
    nickname: '',
    effective_from: '',
    effective_to: '',
    status: 'active',
    tiersText: '',
  }
}

function defaultBindingForm() {
  return {
    id: null,
    feature_id: '',
    included_qty: '0',
    unit: '',
    overage_unit_amount: '0',
  }
}

function defaultFeatureForm() {
  return {
    id: null,
    code: '',
    name: '',
    feature_type: 'boolean',
    unit: '',
    status: 'active',
    description: '',
  }
}

function defaultCouponForm() {
  return {
    id: null,
    code: '',
    name: '',
    description: '',
    coupon_type: 'percent',
    percent: '',
    amount: '',
    currency: 'CNY',
    duration: 'once',
    duration_months: 1,
    max_redemptions: 0,
    valid_from: '',
    valid_until: '',
    status: 'active',
  }
}

function defaultTaxForm() {
  return {
    id: null,
    country: 'CN',
    region: '',
    name: '增值税',
    rate: '',
    effective_from: '',
    effective_to: '',
    enabled: true,
    is_default: false,
  }
}

function priceSummary(plan) {
  const prices = Array.isArray(plan.prices) ? plan.prices : []
  if (!prices.length) return '未配置'
  return prices
    .slice(0, 2)
    .map((p) => `${p.currency} ${p.amount}`)
    .join(' / ')
}

function couponDiscount(row) {
  if (row.coupon_type === 'percent') return `${row.percent}%`
  return formatMoney(row.amount, row.currency)
}

function couponDuration(row) {
  if (row.duration === 'once') return '仅一次'
  if (row.duration === 'forever') return '永久'
  return `重复 ${row.duration_months || 1} 期`
}

function couponValidity(row) {
  if (!row.valid_from && !row.valid_until) return '长期有效'
  return `${formatDate(row.valid_from)} ~ ${formatDate(row.valid_until)}`
}

async function loadPlans() {
  planLoading.value = true
  planError.value = ''
  planUnavailable.value = ''
  try {
    const params = { page: planPage.value, page_size: planPageSize.value }
    if (planQ.value.trim()) params.q = planQ.value.trim()
    if (planStatus.value) params.status = planStatus.value
    if (planPeriod.value) params.billing_period = planPeriod.value
    const data = await billingApi.list('plans/', params)
    plans.value = data.items || []
    planCount.value = data.count || 0
    planPage.value = data.page || planPage.value
  } catch (e) {
    plans.value = []
    planCount.value = 0
    if (isUnavailable(e)) {
      planUnavailable.value = '套餐列表端点缺失（404/405）'
    } else {
      planError.value = e?.message || '套餐列表加载失败'
      app.toastMsg(planError.value, 'error')
    }
  } finally {
    planLoading.value = false
  }
}

async function loadDetail(id) {
  if (!id) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await billingApi.get(`plans/${id}/`)
  } catch (e) {
    detail.value = null
    detailError.value = e?.message || '套餐详情加载失败'
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function loadFeatures() {
  featureLoading.value = true
  featureError.value = ''
  try {
    const params = { page: featurePage.value, page_size: featurePageSize.value }
    if (featureQ.value.trim()) params.q = featureQ.value.trim()
    if (featureStatus.value) params.status = featureStatus.value
    const data = await billingApi.list('features/', params)
    features.value = data.items || []
    featureCount.value = data.count || 0
    featurePage.value = data.page || featurePage.value
  } catch (e) {
    features.value = []
    featureCount.value = 0
    featureError.value = isUnavailable(e)
      ? '功能项端点缺失（404/405）'
      : (e?.message || '功能项加载失败')
  } finally {
    featureLoading.value = false
  }
}

async function loadFeatureOptions() {
  try {
    const data = await billingApi.list('features/', { page: 1, page_size: 200 })
    featureOptions.value = data.items || []
  } catch (e) {
    featureOptions.value = []
  }
}

async function loadCoupons() {
  couponLoading.value = true
  couponError.value = ''
  couponUnavailable.value = ''
  try {
    const params = { page: couponPage.value, page_size: couponPageSize.value }
    if (couponQ.value.trim()) params.q = couponQ.value.trim()
    if (couponStatus.value) params.status = couponStatus.value
    const data = await billingApi.list('coupons/', params)
    coupons.value = data.items || []
    couponCount.value = data.count || 0
    couponPage.value = data.page || couponPage.value
  } catch (e) {
    coupons.value = []
    couponCount.value = 0
    if (isUnavailable(e)) {
      couponUnavailable.value = '优惠券端点缺失（404/405）'
    } else {
      couponError.value = e?.message || '优惠券加载失败'
    }
  } finally {
    couponLoading.value = false
  }
}

async function loadTaxes() {
  taxLoading.value = true
  taxError.value = ''
  taxUnavailable.value = ''
  try {
    const params = { page: taxPage.value, page_size: taxPageSize.value }
    if (taxQ.value.trim()) params.q = taxQ.value.trim()
    if (taxEnabled.value) params.enabled = taxEnabled.value
    const data = await billingApi.list('tax-rates/', params)
    taxes.value = data.items || []
    taxCount.value = data.count || 0
    taxPage.value = data.page || taxPage.value
  } catch (e) {
    taxes.value = []
    taxCount.value = 0
    if (isUnavailable(e)) {
      taxUnavailable.value = '税率端点缺失（404/405）'
    } else {
      taxError.value = e?.message || '税率加载失败'
    }
  } finally {
    taxLoading.value = false
  }
}

function switchSubTab(key) {
  if (subTab.value === key) return
  subTab.value = key
  if (key === 'features' && !features.value.length) loadFeatures()
  if (key === 'coupons' && !coupons.value.length) loadCoupons()
  if (key === 'tax' && !taxes.value.length) loadTaxes()
}

function searchPlans() {
  planPage.value = 1
  loadPlans()
}

function gotoPlanPage(next) {
  const target = Math.min(Math.max(1, Number(next) || 1), planPages.value)
  if (target === planPage.value) return
  planPage.value = target
  loadPlans()
}

function changePlanPageSize(event) {
  planPageSize.value = Math.min(200, Math.max(1, Number(event?.target?.value) || 20))
  planPage.value = 1
  loadPlans()
}

function searchFeatures() {
  featurePage.value = 1
  loadFeatures()
}

function gotoFeaturePage(next) {
  featurePage.value = Math.min(Math.max(1, Number(next) || 1), featurePages.value)
  loadFeatures()
}

function searchCoupons() {
  couponPage.value = 1
  loadCoupons()
}

function gotoCouponPage(next) {
  couponPage.value = Math.min(Math.max(1, Number(next) || 1), couponPages.value)
  loadCoupons()
}

function searchTaxes() {
  taxPage.value = 1
  loadTaxes()
}

function gotoTaxPage(next) {
  taxPage.value = Math.min(Math.max(1, Number(next) || 1), taxPages.value)
  loadTaxes()
}

function openPlan(row) {
  planForm.value = row
    ? {
        id: row.id,
        code: row.code,
        name: row.name,
        description: row.description || '',
        billing_period: row.billing_period,
        trial_days: row.trial_days || 0,
        sort_order: row.sort_order || 0,
        status: row.status,
        limitsText: JSON.stringify(row.limits || {}, null, 2),
      }
    : defaultPlanForm()
  planFormError.value = ''
  planModalOpen.value = true
}

function closePlan() {
  if (planSaving.value) return
  planModalOpen.value = false
}

async function savePlan() {
  planFormError.value = ''
  if (!planForm.value.code.trim()) {
    planFormError.value = '请填写套餐编码'
    return
  }
  if (!planForm.value.name.trim()) {
    planFormError.value = '请填写套餐名称'
    return
  }
  planSaving.value = true
  try {
    const limits = parseObject(planForm.value.limitsText, '功能上限')
    const payload = {
      code: planForm.value.code.trim(),
      name: planForm.value.name.trim(),
      description: planForm.value.description,
      billing_period: planForm.value.billing_period,
      trial_days: Number(planForm.value.trial_days) || 0,
      sort_order: Number(planForm.value.sort_order) || 0,
      status: planForm.value.status,
      limits,
    }
    let saved
    if (planForm.value.id) {
      saved = await billingApi.update(`plans/${planForm.value.id}/update/`, payload)
      app.toastMsg('套餐已更新', 'success')
    } else {
      saved = await billingApi.create('plans/create/', payload)
      app.toastMsg('套餐已创建', 'success')
    }
    planModalOpen.value = false
    await loadPlans()
    await loadFeatureOptions()
    if (saved?.id) {
      detailId.value = saved.id
      detailOpen.value = true
      loadDetail(saved.id)
    }
  } catch (e) {
    planFormError.value = e?.message || '保存套餐失败'
    app.toastMsg(planFormError.value, 'error')
  } finally {
    planSaving.value = false
  }
}

async function planAction(row, action) {
  if (!row?.id) return
  busyPlanId.value = row.id
  try {
    const result = await billingApi.action(`plans/${row.id}/${action}/`, {})
    const text = { publish: '套餐已发布', archive: '套餐已停用', clone: '套餐已克隆为草稿' }[action] || '操作成功'
    app.toastMsg(text, 'success')
    await loadPlans()
    await loadFeatureOptions()
    if (detailOpen.value) {
      if (action === 'clone' && result?.id) {
        detailId.value = result.id
        loadDetail(result.id)
      } else if (detailId.value === row.id) {
        loadDetail(row.id)
      }
    }
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    busyPlanId.value = null
  }
}

function openDetail(row) {
  detailId.value = row.id
  detailOpen.value = true
  loadDetail(row.id)
}

function closeDetail() {
  detailOpen.value = false
}

function openPrice(price) {
  if (!detail.value?.id) {
    app.toastMsg('请先打开套餐详情', 'warning')
    return
  }
  priceForm.value = price
    ? {
        id: price.id,
        currency: price.currency,
        amount: price.amount,
        billing_mode: price.billing_mode,
        nickname: price.nickname || '',
        effective_from: price.effective_from || '',
        effective_to: price.effective_to || '',
        status: price.status,
        tiersText: JSON.stringify(price.tiers || [], null, 2),
      }
    : defaultPriceForm()
  priceFormError.value = ''
  priceModalOpen.value = true
}

function closePrice() {
  if (priceSaving.value) return
  priceModalOpen.value = false
}

async function savePrice() {
  priceFormError.value = ''
  if (!priceForm.value.currency.trim()) {
    priceFormError.value = '请填写币种'
    return
  }
  priceSaving.value = true
  try {
    const payload = {
      currency: priceForm.value.currency.trim().toUpperCase(),
      billing_mode: priceForm.value.billing_mode,
      nickname: priceForm.value.nickname,
      status: priceForm.value.status,
      effective_from: priceForm.value.effective_from || null,
      effective_to: priceForm.value.effective_to || null,
    }
    if (priceForm.value.billing_mode === 'tiered') {
      payload.tiers = parseArray(priceForm.value.tiersText, '阶梯配置')
    } else {
      if (!String(priceForm.value.amount || '').trim()) {
        priceFormError.value = '请填写金额'
        priceSaving.value = false
        return
      }
      payload.amount = priceForm.value.amount
    }
    if (priceForm.value.id) {
      await billingApi.update(`prices/${priceForm.value.id}/update/`, payload)
      app.toastMsg('价格已更新', 'success')
    } else {
      payload.plan_id = detail.value.id
      await billingApi.create('prices/create/', payload)
      app.toastMsg('价格已创建', 'success')
    }
    priceModalOpen.value = false
    await loadDetail(detail.value.id)
    await loadPlans()
  } catch (e) {
    priceFormError.value = e?.message || '保存价格失败'
    app.toastMsg(priceFormError.value, 'error')
  } finally {
    priceSaving.value = false
  }
}

function openBinding(binding) {
  if (!detail.value?.id) return
  bindingForm.value = binding
    ? {
        id: binding.id,
        feature_id: binding.feature_id,
        included_qty: binding.included_qty,
        unit: binding.unit || '',
        overage_unit_amount: binding.overage_unit_amount,
      }
    : defaultBindingForm()
  bindingError.value = ''
  bindingModalOpen.value = true
  if (!featureOptions.value.length) loadFeatureOptions()
}

function closeBinding() {
  if (bindingSaving.value) return
  bindingModalOpen.value = false
}

async function saveBinding() {
  bindingError.value = ''
  if (!bindingForm.value.id && !bindingForm.value.feature_id) {
    bindingError.value = '请选择功能项'
    return
  }
  bindingSaving.value = true
  try {
    const payload = {
      included_qty: bindingForm.value.included_qty || '0',
      overage_unit_amount: bindingForm.value.overage_unit_amount || '0',
      unit: bindingForm.value.unit,
    }
    if (bindingForm.value.id) {
      await billingApi.update(`plan-features/${bindingForm.value.id}/update/`, payload)
      app.toastMsg('功能包含量已更新', 'success')
    } else {
      payload.plan_id = detail.value.id
      payload.feature_id = Number(bindingForm.value.feature_id)
      await billingApi.create('plan-features/create/', payload)
      app.toastMsg('功能已绑定', 'success')
    }
    bindingModalOpen.value = false
    await loadDetail(detail.value.id)
  } catch (e) {
    bindingError.value = e?.message || '保存绑定失败'
    app.toastMsg(bindingError.value, 'error')
  } finally {
    bindingSaving.value = false
  }
}

function openFeature(row) {
  featureForm.value = row
    ? {
        id: row.id,
        code: row.code,
        name: row.name,
        feature_type: row.feature_type,
        unit: row.unit || '',
        status: row.status,
        description: row.description || '',
      }
    : defaultFeatureForm()
  featureFormError.value = ''
  featureModalOpen.value = true
}

function closeFeature() {
  if (featureSaving.value) return
  featureModalOpen.value = false
}

async function saveFeature() {
  featureFormError.value = ''
  if (!featureForm.value.code.trim()) {
    featureFormError.value = '请填写功能编码'
    return
  }
  if (!featureForm.value.name.trim()) {
    featureFormError.value = '请填写功能名称'
    return
  }
  featureSaving.value = true
  try {
    const payload = {
      code: featureForm.value.code.trim(),
      name: featureForm.value.name.trim(),
      feature_type: featureForm.value.feature_type,
      unit: featureForm.value.unit,
      status: featureForm.value.status,
      description: featureForm.value.description,
    }
    if (featureForm.value.id) {
      await billingApi.update(`features/${featureForm.value.id}/update/`, payload)
      app.toastMsg('功能项已更新', 'success')
    } else {
      await billingApi.create('features/create/', payload)
      app.toastMsg('功能项已创建', 'success')
    }
    featureModalOpen.value = false
    await loadFeatures()
    await loadFeatureOptions()
  } catch (e) {
    featureFormError.value = e?.message || '保存功能项失败'
    app.toastMsg(featureFormError.value, 'error')
  } finally {
    featureSaving.value = false
  }
}

function openCoupon(row) {
  couponForm.value = row
    ? {
        id: row.id,
        code: row.code,
        name: row.name,
        description: row.description || '',
        coupon_type: row.coupon_type,
        percent: row.percent,
        amount: row.amount,
        currency: row.currency,
        duration: row.duration,
        duration_months: row.duration_months || 1,
        max_redemptions: row.max_redemptions || 0,
        valid_from: String(row.valid_from || '').slice(0, 16),
        valid_until: String(row.valid_until || '').slice(0, 16),
        status: row.status,
      }
    : defaultCouponForm()
  couponFormError.value = ''
  couponModalOpen.value = true
}

function closeCoupon() {
  if (couponSaving.value) return
  couponModalOpen.value = false
}

async function saveCoupon() {
  couponFormError.value = ''
  if (!couponForm.value.code.trim()) {
    couponFormError.value = '请填写优惠码'
    return
  }
  if (!couponForm.value.name.trim()) {
    couponFormError.value = '请填写优惠券名称'
    return
  }
  if (couponForm.value.coupon_type === 'percent' && !String(couponForm.value.percent || '').trim()) {
    couponFormError.value = '请填写折扣百分比'
    return
  }
  if (couponForm.value.coupon_type === 'fixed' && !String(couponForm.value.amount || '').trim()) {
    couponFormError.value = '请填写固定减免金额'
    return
  }
  couponSaving.value = true
  try {
    const payload = {
      code: couponForm.value.code.trim(),
      name: couponForm.value.name.trim(),
      description: couponForm.value.description,
      coupon_type: couponForm.value.coupon_type,
      currency: couponForm.value.currency || 'CNY',
      duration: couponForm.value.duration,
      duration_months: Number(couponForm.value.duration_months) || 1,
      max_redemptions: Number(couponForm.value.max_redemptions) || 0,
      status: couponForm.value.status,
    }
    if (couponForm.value.coupon_type === 'percent') payload.percent = couponForm.value.percent
    if (couponForm.value.coupon_type === 'fixed') payload.amount = couponForm.value.amount
    if (couponForm.value.valid_from) payload.valid_from = isoText(couponForm.value.valid_from)
    if (couponForm.value.valid_until) payload.valid_until = isoText(couponForm.value.valid_until)
    if (couponForm.value.id) {
      await billingApi.update(`coupons/${couponForm.value.id}/update/`, payload)
      app.toastMsg('优惠券已更新', 'success')
    } else {
      await billingApi.create('coupons/create/', payload)
      app.toastMsg('优惠券已创建', 'success')
    }
    couponModalOpen.value = false
    await loadCoupons()
  } catch (e) {
    couponFormError.value = e?.message || '保存优惠券失败'
    app.toastMsg(couponFormError.value, 'error')
  } finally {
    couponSaving.value = false
  }
}

function openTax(row) {
  taxForm.value = row
    ? {
        id: row.id,
        country: row.country,
        region: row.region || '',
        name: row.name,
        rate: row.rate,
        effective_from: row.effective_from || '',
        effective_to: row.effective_to || '',
        enabled: Boolean(row.enabled),
        is_default: Boolean(row.is_default),
      }
    : defaultTaxForm()
  taxFormError.value = ''
  taxModalOpen.value = true
}

function closeTax() {
  if (taxSaving.value) return
  taxModalOpen.value = false
}

async function saveTax() {
  taxFormError.value = ''
  if (!taxForm.value.country.trim()) {
    taxFormError.value = '请填写国家/地区代码'
    return
  }
  const rate = Number(taxForm.value.rate)
  if (!Number.isFinite(rate) || rate < 0 || rate > 100) {
    taxFormError.value = '税率必须在 0 到 100 之间'
    return
  }
  taxSaving.value = true
  try {
    const payload = {
      country: taxForm.value.country.trim().toUpperCase(),
      region: taxForm.value.region,
      name: taxForm.value.name || '增值税',
      rate,
      effective_from: taxForm.value.effective_from || null,
      effective_to: taxForm.value.effective_to || null,
      enabled: Boolean(taxForm.value.enabled),
      is_default: Boolean(taxForm.value.is_default),
    }
    if (taxForm.value.id) {
      await billingApi.update(`tax-rates/${taxForm.value.id}/update/`, payload)
      app.toastMsg('税率已更新', 'success')
    } else {
      await billingApi.create('tax-rates/create/', payload)
      app.toastMsg('税率已创建', 'success')
    }
    taxModalOpen.value = false
    await loadTaxes()
  } catch (e) {
    taxFormError.value = e?.message || '保存税率失败'
    app.toastMsg(taxFormError.value, 'error')
  } finally {
    taxSaving.value = false
  }
}

function askDelete(kind, row) {
  confirmKind.value = kind
  confirmRow.value = row
  confirmError.value = ''
  confirmOpen.value = true
}

function closeConfirm() {
  if (confirmBusy.value) return
  confirmOpen.value = false
}

async function submitConfirm() {
  if (!confirmRow.value) return
  confirmBusy.value = true
  confirmError.value = ''
  try {
    const row = confirmRow.value
    if (confirmKind.value === 'plan') {
      await billingApi.remove(`plans/${row.id}/delete/`)
      app.toastMsg('套餐已删除', 'success')
      if (detailId.value === row.id) detailOpen.value = false
      await loadPlans()
    } else if (confirmKind.value === 'price') {
      await billingApi.remove(`prices/${row.id}/delete/`)
      app.toastMsg('价格已删除', 'success')
      if (detail.value?.id) await loadDetail(detail.value.id)
      await loadPlans()
    } else if (confirmKind.value === 'binding') {
      await billingApi.remove(`plan-features/${row.id}/delete/`)
      app.toastMsg('功能已解绑', 'success')
      if (detail.value?.id) await loadDetail(detail.value.id)
    } else if (confirmKind.value === 'feature') {
      await billingApi.remove(`features/${row.id}/delete/`)
      app.toastMsg('功能项已删除', 'success')
      await loadFeatures()
      await loadFeatureOptions()
    } else if (confirmKind.value === 'coupon') {
      await billingApi.remove(`coupons/${row.id}/delete/`)
      app.toastMsg('优惠券已删除', 'success')
      await loadCoupons()
    } else if (confirmKind.value === 'tax') {
      await billingApi.remove(`tax-rates/${row.id}/delete/`)
      app.toastMsg('税率已删除', 'success')
      await loadTaxes()
    }
    confirmOpen.value = false
  } catch (e) {
    confirmError.value = e?.message || '删除失败'
    app.toastMsg(confirmError.value, 'error')
  } finally {
    confirmBusy.value = false
  }
}

watch(() => props.reloadToken, () => {
  loadPlans()
  loadFeatureOptions()
  if (subTab.value === 'features') loadFeatures()
  if (subTab.value === 'coupons') loadCoupons()
  if (subTab.value === 'tax') loadTaxes()
  if (detail.value?.id) loadDetail(detail.value.id)
})

onMounted(() => {
  loadPlans()
  loadFeatureOptions()
})
</script>