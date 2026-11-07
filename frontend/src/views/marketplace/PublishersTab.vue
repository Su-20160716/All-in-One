<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-1.5">
      <button
        v-for="item in SECTIONS"
        :key="item.key"
        class="rounded-pill px-3 py-1.5 text-[12px] transition-colors"
        :class="section === item.key
          ? 'bg-brand-600 text-white'
          : 'border border-ink-200 bg-white text-ink-600 hover:border-brand-300 hover:text-brand-600'"
        @click="section = item.key"
      >
        {{ item.label }}
      </button>
      <span class="tag">我的发布者 {{ fmtNum(myPublishers.length) }}</span>
      <button class="btn-outline ml-auto py-1 text-[12px]" :disabled="loading || myLoading" @click="reloadCurrent">
        刷新
      </button>
    </div>

    <template v-if="section === 'publishers'">
      <div class="card space-y-2 p-3">
        <div class="flex flex-wrap items-center gap-2">
          <input
            v-model="q"
            class="input w-full sm:w-[240px]"
            placeholder="搜索发布者名称或标识"
            aria-label="搜索发布者"
          />
          <select v-model="status" class="input w-[130px] py-1" aria-label="发布者状态">
            <option value="">全部状态</option>
            <option value="pending">待认证</option>
            <option value="verified">已认证</option>
            <option value="suspended">已暂停</option>
          </select>
          <button class="btn-ghost py-1 text-[12px]" @click="resetPublisherFilters">重置</button>
          <div class="ml-auto flex items-center gap-1.5">
            <button class="btn-primary py-1 text-[12px]" @click="openPublisherCreate">申请入驻</button>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-400">
          <span class="tag">共 {{ fmtNum(publisherTotal) }} 个发布者</span>
          <span class="tag">已认证 {{ fmtNum(verifiedCount) }}</span>
          <span class="tag">待认证 {{ fmtNum(pendingCount) }}</span>
        </div>
      </div>

      <div
        v-if="publisherError"
        class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1 truncate">{{ publisherError }}</span>
        <button class="shrink-0 font-medium" @click="loadPublishers">重试</button>
      </div>
      <div v-else-if="loading && !publishers.length" class="card py-14 text-center text-[12px] text-ink-400">
        发布者加载中…
      </div>
      <div v-else-if="!publishers.length" class="card rounded-control border-dashed py-14 text-center text-[12px] text-ink-400">
        暂无发布者，可点击「申请入驻」成为首个发布者
      </div>
      <div v-else class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <article v-for="row in publishers" :key="row.id" class="card flex flex-col gap-2 p-4">
          <div class="flex items-start gap-2">
            <span class="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-brand-50 text-[14px] font-semibold text-brand-700">
              {{ (row.name || '发').slice(0, 1) }}
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="truncate text-[14px] font-semibold text-ink-900">{{ row.name }}</span>
                <span class="tag" :class="publisherClass(row.status)">{{ publisherLabel(row.status) }}</span>
                <span v-if="row.owner_id === userStore.profile?.id" class="tag bg-brand-50 text-brand-700">我的</span>
              </div>
              <div class="truncate text-[11px] text-ink-400">{{ row.slug }}</div>
            </div>
          </div>
          <p class="line-clamp-2 min-h-[32px] text-[12px] leading-relaxed text-ink-500">
            {{ row.summary || '该发布者暂未填写简介' }}
          </p>
          <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-400">
            <span class="tag">分成 {{ fmtPct(row.revenue_share) }}</span>
            <span v-if="row.website" class="tag max-w-[150px] truncate">{{ row.website }}</span>
            <span v-if="row.contact_email" class="tag max-w-[160px] truncate">{{ row.contact_email }}</span>
          </div>
          <div class="mt-auto flex flex-wrap items-center gap-1.5 border-t border-ink-50 pt-2">
            <button class="btn-ghost py-1 text-[11px]" @click="openPublisherDetail(row)">详情</button>
            <button
              v-if="userStore.isAdmin && row.status === 'pending'"
              class="btn-ghost py-1 text-[11px] text-emerald-600"
              @click="verifyPublisher(row)"
            >
              认证
            </button>
            <button
              v-if="userStore.isAdmin && row.status !== 'suspended'"
              class="btn-ghost py-1 text-[11px] text-rose-600"
              @click="openSuspend(row)"
            >
              暂停
            </button>
            <button class="btn-ghost ml-auto py-1 text-[11px]" @click="usePublisher(row)">
              经营数据
            </button>
          </div>
        </article>
      </div>

      <div v-if="publisherTotal > 0" class="flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-500">
        <span>第 {{ publisherPage }} / {{ publisherPages }} 页</span>
        <div class="flex items-center gap-1.5">
          <button class="btn-outline py-1 text-[12px]" :disabled="publisherPage <= 1 || loading" @click="goPublisherPage(publisherPage - 1)">上一页</button>
          <button class="btn-outline py-1 text-[12px]" :disabled="publisherPage >= publisherPages || loading" @click="goPublisherPage(publisherPage + 1)">下一页</button>
        </div>
      </div>
    </template>

    <template v-else-if="section === 'apps'">
      <div class="card space-y-2 p-3">
        <div class="flex flex-wrap items-center gap-2">
          <select v-model="activePublisherId" class="input w-[240px] py-1" aria-label="选择发布者">
            <option value="">选择发布者</option>
            <option v-for="row in myPublishers" :key="row.id" :value="String(row.id)">
              {{ row.name }}（{{ publisherLabel(row.status) }}）
            </option>
          </select>
          <select v-model="appStatus" class="input w-[130px] py-1" aria-label="应用状态">
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="reviewing">审核中</option>
            <option value="published">已上架</option>
            <option value="suspended">已暂停</option>
            <option value="delisted">已下架</option>
          </select>
          <button class="btn-ghost py-1 text-[12px]" :disabled="appLoading" @click="loadApps">刷新</button>
          <div class="ml-auto">
            <button class="btn-primary py-1 text-[12px]" :disabled="!activePublisherId" @click="openAppCreate">
              创建应用
            </button>
          </div>
        </div>
        <p class="text-[11px] text-ink-400">
          应用需先创建版本并提交审核，审核通过后上架；版本发布与上下架状态以服务端为准
        </p>
      </div>

      <div v-if="!myPublishers.length" class="card rounded-control border-dashed py-14 text-center text-[12px] text-ink-400">
        当前账号还没有发布者身份，请先在「发布者」页签申请入驻
      </div>
      <div v-else-if="appError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1 truncate">{{ appError }}</span>
        <button class="shrink-0 font-medium" @click="loadApps">重试</button>
      </div>
      <div v-else-if="appLoading && !apps.length" class="card py-14 text-center text-[12px] text-ink-400">
        应用加载中…
      </div>
      <div v-else-if="!apps.length" class="card rounded-control border-dashed py-14 text-center text-[12px] text-ink-400">
        该发布者下暂无应用，点击「创建应用」开始发布
      </div>
      <SectionCard v-else title="应用管理" :subtitle="`当前发布者共 ${apps.length} 个应用`">
        <template #actions>
          <span class="tag">上架 {{ fmtNum(publishedAppCount) }}</span>
          <span class="tag">审核中 {{ fmtNum(reviewingAppCount) }}</span>
        </template>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[960px]">
            <thead class="border-b border-ink-100 bg-ink-50/60">
              <tr>
                <th class="th">应用</th>
                <th class="th">状态</th>
                <th class="th">最新版本</th>
                <th class="th text-right">安装量</th>
                <th class="th text-right">评分</th>
                <th class="th">更新时间</th>
                <th class="th text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in apps" :key="row.id">
                <td class="td">
                  <div class="max-w-[230px] truncate font-medium text-ink-800">{{ row.name }}</div>
                  <div class="max-w-[230px] truncate text-[11px] text-ink-400">{{ row.code }} · {{ row.category?.name || '未分类' }}</div>
                </td>
                <td class="td">
                  <span class="tag" :class="listingClass(row.status)">{{ listingLabel(row.status) }}</span>
                </td>
                <td class="td">
                  <span class="font-mono text-[12px]">{{ row.latest_version?.version || '—' }}</span>
                  <span v-if="row.latest_version?.breaking" class="ml-1 tag bg-rose-50 text-rose-600">破坏性</span>
                </td>
                <td class="td text-right">{{ fmtNum(row.install_count) }}</td>
                <td class="td text-right">{{ fmtRating(row.rating) }}</td>
                <td class="td text-[11px] text-ink-500">{{ fmtDate(row.updated_at, true) }}</td>
                <td class="td">
                  <div class="flex flex-wrap justify-end gap-1">
                    <button class="btn-ghost py-0.5 text-[11px]" @click="openVersions(row)">版本</button>
                    <button
                      v-if="['draft', 'delisted', 'suspended'].includes(row.status)"
                      class="btn-ghost py-0.5 text-[11px]"
                      @click="submitListing(row)"
                    >
                      提交审核
                    </button>
                    <button
                      v-if="row.status === 'reviewing'"
                      class="btn-ghost py-0.5 text-[11px]"
                      @click="withdrawListing(row)"
                    >
                      撤回
                    </button>
                    <button
                      v-if="['delisted', 'suspended'].includes(row.status)"
                      class="btn-ghost py-0.5 text-[11px] text-emerald-600"
                      @click="publishListing(row)"
                    >
                      上架
                    </button>
                    <button
                      v-if="row.status === 'published'"
                      class="btn-ghost py-0.5 text-[11px] text-rose-600"
                      @click="delistListing(row)"
                    >
                      下架
                    </button>
                    <template v-if="userStore.isAdmin && row.status === 'reviewing'">
                      <button class="btn-ghost py-0.5 text-[11px] text-emerald-600" @click="approveListing(row)">通过</button>
                      <button class="btn-ghost py-0.5 text-[11px] text-rose-600" @click="openReject(row)">驳回</button>
                    </template>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </template>

    <template v-else>
      <div class="card space-y-2 p-3">
        <div class="flex flex-wrap items-center gap-2">
          <select v-model="activePublisherId" class="input w-[260px] py-1" aria-label="选择发布者">
            <option value="">选择发布者</option>
            <option v-for="row in myPublishers" :key="row.id" :value="String(row.id)">
              {{ row.name }}（{{ publisherLabel(row.status) }}）
            </option>
          </select>
          <span v-if="activePublisher" class="tag" :class="publisherClass(activePublisher.status)">
            {{ publisherLabel(activePublisher.status) }}
          </span>
          <span v-if="revenueData" class="tag">分成 {{ fmtPct(revenueData.revenue?.share_pct) }}</span>
          <button class="btn-outline ml-auto py-1 text-[12px]" :disabled="revenueLoading" @click="loadRevenue">
            {{ revenueLoading ? '加载中…' : '刷新收入' }}
          </button>
        </div>
      </div>

      <div v-if="!activePublisherId" class="card rounded-control border-dashed py-14 text-center text-[12px] text-ink-400">
        请选择发布者查看经营数据
      </div>
      <div v-else-if="revenueError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <div class="flex items-center gap-3">
          <span class="min-w-0 flex-1">{{ revenueError }}</span>
          <button class="shrink-0 font-medium" @click="loadRevenue">重试</button>
        </div>
      </div>
      <div v-else-if="revenueLoading && !revenueData" class="card py-14 text-center text-[12px] text-ink-400">
        经营数据加载中…
      </div>
      <template v-else-if="revenueData">
        <StatsGrid :items="revenueKpis" :loading="revenueLoading" :skeleton-count="4" />

        <div class="grid gap-3 lg:grid-cols-2">
          <SectionCard title="分成与退款" subtitle="成交额扣除退款后，按发布者分成比例结算">
            <div class="grid grid-cols-2 gap-2">
              <div class="rounded-control bg-ink-50/60 px-3 py-2">
                <div class="text-[11px] text-ink-400">订单数</div>
                <div class="text-[15px] font-semibold text-ink-800">{{ fmtNum(revenueData.revenue?.orders) }}</div>
              </div>
              <div class="rounded-control bg-ink-50/60 px-3 py-2">
                <div class="text-[11px] text-ink-400">退款订单</div>
                <div class="text-[15px] font-semibold text-ink-800">{{ fmtNum(revenueData.revenue?.refunded_orders) }}</div>
              </div>
              <div class="rounded-control bg-ink-50/60 px-3 py-2">
                <div class="text-[11px] text-ink-400">退款冲减</div>
                <div class="text-[15px] font-semibold text-rose-600">{{ fmtMoney(revenueData.revenue?.refund) }}</div>
              </div>
              <div class="rounded-control bg-ink-50/60 px-3 py-2">
                <div class="text-[11px] text-ink-400">平台抽成</div>
                <div class="text-[15px] font-semibold text-ink-800">{{ fmtMoney(revenueData.revenue?.platform_fee) }}</div>
              </div>
            </div>
            <div class="mt-3">
              <div class="mb-1 text-[12px] font-medium text-ink-600">按币种汇总</div>
              <div v-if="!(revenueCurrencyRows || []).length" class="py-3 text-center text-[12px] text-ink-400">暂无订单</div>
              <table v-else class="w-full">
                <thead>
                  <tr>
                    <th class="th">币种</th>
                    <th class="th text-right">流水</th>
                    <th class="th text-right">退款</th>
                    <th class="th text-right">发布者净收入</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="row in revenueCurrencyRows" :key="row.currency">
                    <td class="td">{{ row.currency }}</td>
                    <td class="td text-right">{{ fmtMoney(row.gross, row.currency) }}</td>
                    <td class="td text-right text-rose-600">{{ fmtMoney(row.refund, row.currency) }}</td>
                    <td class="td text-right">{{ fmtMoney(row.publisher_net, row.currency) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="应用收入排行" subtitle="按发布者净收入排序，便于定位主力应用">
            <div v-if="!(revenueData.revenue?.by_listing || []).length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
              暂无成交记录
            </div>
            <div v-else class="divide-y divide-ink-50">
              <div
                v-for="(row, index) in revenueData.revenue.by_listing"
                :key="row.code"
                class="flex items-center gap-2 py-1.5 text-[12px]"
              >
                <span class="w-5 shrink-0 text-ink-400">{{ index + 1 }}</span>
                <span class="min-w-0 flex-1 truncate text-ink-700">{{ row.name }}</span>
                <span class="shrink-0 text-ink-400">{{ fmtNum(row.orders) }} 单</span>
                <span class="w-24 shrink-0 text-right text-ink-800">{{ fmtMoney(row.publisher_net) }}</span>
              </div>
            </div>
          </SectionCard>
        </div>

        <SectionCard title="经营指标" subtitle="应用结构、安装规模与评分概览">
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div class="rounded-control border border-ink-100 px-3 py-2">
              <div class="text-[11px] text-ink-400">应用总数</div>
              <div class="text-[18px] font-semibold text-ink-900">{{ fmtNum(revenueData.listings?.total) }}</div>
              <div class="text-[11px] text-ink-400">已上架 {{ fmtNum(revenueData.listings?.published) }}</div>
            </div>
            <div class="rounded-control border border-ink-100 px-3 py-2">
              <div class="text-[11px] text-ink-400">有效安装</div>
              <div class="text-[18px] font-semibold text-ink-900">{{ fmtNum(revenueData.installs?.active) }}</div>
              <div class="text-[11px] text-ink-400">计数器 {{ fmtNum(revenueData.installs?.total_counters) }}</div>
            </div>
            <div class="rounded-control border border-ink-100 px-3 py-2">
              <div class="text-[11px] text-ink-400">评价数</div>
              <div class="text-[18px] font-semibold text-ink-900">{{ fmtNum(revenueData.ratings?.reviews) }}</div>
              <div class="text-[11px] text-ink-400">平均 {{ fmtRating(revenueData.ratings?.average) }} 分</div>
            </div>
            <div class="rounded-control border border-ink-100 px-3 py-2">
              <div class="text-[11px] text-ink-400">发布者净收入</div>
              <div class="text-[18px] font-semibold text-emerald-600">{{ fmtMoney(revenueData.revenue?.publisher_net_cny) }}</div>
              <div class="text-[11px] text-ink-400">折算人民币</div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="结算信息" subtitle="银行与结算周期仅用于本地模拟，提交后立即写入发布者档案">
          <div class="grid gap-2 sm:grid-cols-2">
            <label class="text-[12px] text-ink-500">
              银行名称
              <input v-model="settlementForm.bank_name" class="input mt-1" placeholder="开户行" />
            </label>
            <label class="text-[12px] text-ink-500">
              账户名称
              <input v-model="settlementForm.account_name" class="input mt-1" placeholder="账户名" />
            </label>
            <label class="text-[12px] text-ink-500">
              账号
              <input v-model="settlementForm.account_no" class="input mt-1" placeholder="结算账号" />
            </label>
            <label class="text-[12px] text-ink-500">
              结算周期
              <input v-model="settlementForm.cycle" class="input mt-1" placeholder="例如 monthly" />
            </label>
            <label class="text-[12px] text-ink-500">
              税号
              <input v-model="settlementForm.tax_no" class="input mt-1" placeholder="纳税人识别号" />
            </label>
            <label class="text-[12px] text-ink-500">
              联系人
              <input v-model="settlementForm.contact" class="input mt-1" placeholder="结算联系人" />
            </label>
          </div>
          <div class="mt-2 flex justify-end">
            <button class="btn-primary py-1 text-[12px]" :disabled="settlementSaving" @click="saveSettlement">
              {{ settlementSaving ? '保存中…' : '保存结算信息' }}
            </button>
          </div>
        </SectionCard>
      </template>
    </template>

    <Modal :show="publisherCreateOpen" title="申请成为发布者" width="540px" @close="closePublisherCreate">
      <div class="space-y-2">
        <label class="block text-[12px] text-ink-500">
          发布者名称
          <input v-model="publisherForm.name" class="input mt-1" maxlength="120" placeholder="团队或公司名称" />
        </label>
        <label class="block text-[12px] text-ink-500">
          标识（可选）
          <input v-model="publisherForm.slug" class="input mt-1" placeholder="留空自动生成" />
        </label>
        <label class="block text-[12px] text-ink-500">
          简介
          <textarea v-model="publisherForm.summary" class="input mt-1 min-h-[64px]" maxlength="500"></textarea>
        </label>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-500">
            官网
            <input v-model="publisherForm.website" class="input mt-1" placeholder="https://" />
          </label>
          <label class="block text-[12px] text-ink-500">
            联系邮箱
            <input v-model="publisherForm.contact_email" class="input mt-1" placeholder="name@example.com" />
          </label>
        </div>
        <p class="text-[11px] text-ink-400">提交后状态为待认证，认证通过后可获得认证标识与结算资格。</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closePublisherCreate">取消</button>
          <button class="btn-primary" :disabled="publisherSaving" @click="createPublisher">
            {{ publisherSaving ? '提交中…' : '提交申请' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="publisherDetailOpen" title="发布者详情" width="600px" @close="publisherDetailOpen = false">
      <div v-if="publisherDetail" class="space-y-3">
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="tag" :class="publisherClass(publisherDetail.status)">{{ publisherLabel(publisherDetail.status) }}</span>
          <span class="tag">分成 {{ fmtPct(publisherDetail.revenue_share) }}</span>
          <span class="text-[11px] text-ink-400">{{ publisherDetail.slug }}</span>
        </div>
        <p class="text-[12px] leading-relaxed text-ink-600">{{ publisherDetail.summary || '暂无简介' }}</p>
        <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
          <div class="text-ink-400">官网</div>
          <div class="break-all text-ink-700">{{ publisherDetail.website || '—' }}</div>
          <div class="text-ink-400">联系邮箱</div>
          <div class="break-all text-ink-700">{{ publisherDetail.contact_email || '—' }}</div>
          <div class="text-ink-400">认证时间</div>
          <div class="text-ink-700">{{ fmtDate(publisherDetail.verified_at, true) }}</div>
          <div class="text-ink-400">创建时间</div>
          <div class="text-ink-700">{{ fmtDate(publisherDetail.created_at, true) }}</div>
        </div>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[11px] text-ink-400">应用数</div>
            <div class="text-[14px] font-semibold text-ink-800">{{ fmtNum(publisherDetail.stats?.listings) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[11px] text-ink-400">已上架</div>
            <div class="text-[14px] font-semibold text-ink-800">{{ fmtNum(publisherDetail.stats?.published_listings) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[11px] text-ink-400">安装量</div>
            <div class="text-[14px] font-semibold text-ink-800">{{ fmtNum(publisherDetail.stats?.installs) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
            <div class="text-[11px] text-ink-400">评价数</div>
            <div class="text-[14px] font-semibold text-ink-800">{{ fmtNum(publisherDetail.stats?.reviews) }}</div>
          </div>
        </div>
        <div>
          <div class="mb-1 text-[12px] font-medium text-ink-700">热门应用</div>
          <div v-if="!(publisherDetail.top_listings || []).length" class="py-3 text-center text-[12px] text-ink-400">暂无已上架应用</div>
          <div v-else class="divide-y divide-ink-50">
            <div v-for="row in publisherDetail.top_listings" :key="row.id" class="flex items-center gap-2 py-1.5 text-[12px]">
              <span class="min-w-0 flex-1 truncate text-ink-700">{{ row.name }}</span>
              <span class="text-ink-400">{{ fmtRating(row.rating) }} 分</span>
              <span class="w-20 text-right text-ink-500">安装 {{ fmtNum(row.install_count) }}</span>
            </div>
          </div>
        </div>
        <div v-if="publisherDetail.suspended_reason" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          暂停原因：{{ publisherDetail.suspended_reason }}
        </div>
        <div class="flex justify-end">
          <button class="btn-ghost" @click="publisherDetailOpen = false">关闭</button>
        </div>
      </div>
    </Modal>

    <Modal :show="suspendOpen" title="暂停发布者" width="460px" @close="closeSuspend">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">暂停后该发布者名下的已上架应用会同步暂停，请填写原因。</p>
        <textarea v-model="suspendReason" class="input min-h-[80px]" placeholder="暂停原因（必填）"></textarea>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeSuspend">取消</button>
          <button class="btn-danger" :disabled="suspendSaving" @click="submitSuspend">
            {{ suspendSaving ? '处理中…' : '确认暂停' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="appCreateOpen" title="创建应用" width="620px" @close="closeAppCreate">
      <div class="space-y-2">
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-500">
            应用名称
            <input v-model="appForm.name" class="input mt-1" maxlength="200" placeholder="例如 智能报表助手" />
          </label>
          <label class="block text-[12px] text-ink-500">
            应用标识（可选）
            <input v-model="appForm.code" class="input mt-1" placeholder="留空自动生成" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-500">
          一句话简介
          <input v-model="appForm.summary" class="input mt-1" maxlength="500" />
        </label>
        <label class="block text-[12px] text-ink-500">
          详细介绍
          <textarea v-model="appForm.description" class="input mt-1 min-h-[80px]"></textarea>
        </label>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-500">
            类型
            <select v-model="appForm.type" class="input mt-1">
              <option v-for="row in TYPE_OPTIONS" :key="row.value" :value="row.value">{{ row.label }}</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-500">
            分类
            <select v-model="appForm.category_id" class="input mt-1">
              <option value="">未分类</option>
              <option v-for="row in categories" :key="row.id" :value="String(row.id)">{{ row.name }}</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-500">
            定价模式
            <select v-model="appForm.pricing_mode" class="input mt-1">
              <option value="free">免费</option>
              <option value="paid">付费</option>
              <option value="freemium">免费增值</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-500">
            标签（逗号分隔）
            <input v-model="appForm.tags" class="input mt-1" placeholder="报表,分析" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-500">
          图标地址（可选）
          <input v-model="appForm.icon" class="input mt-1" placeholder="https://" />
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeAppCreate">取消</button>
          <button class="btn-primary" :disabled="appSaving" @click="createApp">
            {{ appSaving ? '创建中…' : '创建草稿' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="versionsOpen" title="版本管理" width="720px" @close="closeVersions">
      <div v-if="versionTarget" class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-ink-800">{{ versionTarget.name }}</span>
          <span class="tag" :class="listingClass(versionTarget.status)">{{ listingLabel(versionTarget.status) }}</span>
          <span class="tag">{{ versionTarget.code }}</span>
          <button class="btn-ghost ml-auto py-1 text-[11px]" :disabled="versionsLoading" @click="loadVersions(versionTarget)">
            刷新版本
          </button>
        </div>

        <div v-if="versionsError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ versionsError }}
        </div>
        <div v-else-if="versionsLoading && !versions.length" class="py-6 text-center text-[12px] text-ink-400">版本加载中…</div>
        <div v-else-if="!versions.length" class="rounded-control border border-dashed border-ink-200 py-6 text-center text-[12px] text-ink-400">
          暂无版本，请先创建一个版本草稿
        </div>
        <div v-else class="max-h-52 overflow-y-auto rounded-control border border-ink-100">
          <table class="w-full">
            <thead class="bg-ink-50/60">
              <tr>
                <th class="th">版本</th>
                <th class="th">状态</th>
                <th class="th">平台下限</th>
                <th class="th">发布时间</th>
                <th class="th text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in versions" :key="row.id">
                <td class="td font-mono">
                  {{ row.version }}
                  <span v-if="row.breaking" class="tag bg-rose-50 text-rose-600">破坏性</span>
                </td>
                <td class="td">
                  <span class="tag" :class="versionClass(row.status)">{{ versionLabel(row.status) }}</span>
                </td>
                <td class="td">≥ {{ row.min_platform_version }}</td>
                <td class="td text-[11px] text-ink-500">{{ fmtDate(row.published_at, true) }}</td>
                <td class="td text-right">
                  <button
                    v-if="row.status === 'draft'"
                    class="btn-ghost py-0.5 text-[11px] text-emerald-600"
                    @click="publishVersion(row)"
                  >
                    发布版本
                  </button>
                  <span v-else class="text-[11px] text-ink-400">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="rounded-control bg-ink-50/60 p-3">
          <div class="mb-2 text-[12px] font-medium text-ink-700">新建版本</div>
          <div class="grid gap-2 sm:grid-cols-2">
            <label class="block text-[12px] text-ink-500">
              版本号
              <input v-model="versionForm.version" class="input mt-1" placeholder="1.0.0" />
            </label>
            <label class="block text-[12px] text-ink-500">
              平台版本下限
              <input v-model="versionForm.min_platform_version" class="input mt-1" placeholder="3.0.0" />
            </label>
            <label class="block text-[12px] text-ink-500">
              包大小（字节）
              <input v-model.number="versionForm.package_size" type="number" min="0" class="input mt-1" />
            </label>
            <label class="flex items-center gap-2 pt-5 text-[12px] text-ink-600">
              <input v-model="versionForm.breaking" type="checkbox" class="h-3.5 w-3.5" />
              标记为破坏性变更
            </label>
          </div>
          <label class="mt-2 block text-[12px] text-ink-500">
            变更说明
            <textarea v-model="versionForm.changelog" class="input mt-1 min-h-[64px]"></textarea>
          </label>
          <div class="mt-2 flex justify-end">
            <button class="btn-primary py-1 text-[12px]" :disabled="versionSaving" @click="createVersion">
              {{ versionSaving ? '创建中…' : '创建版本草稿' }}
            </button>
          </div>
        </div>

        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeVersions">关闭</button>
          <button
            v-if="['draft', 'delisted', 'suspended'].includes(versionTarget.status)"
            class="btn-primary"
            @click="submitListing(versionTarget)"
          >
            提交审核
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="rejectOpen" title="驳回应用" width="460px" @close="closeReject">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">{{ rejectTarget?.name }}</p>
        <textarea v-model="rejectReason" class="input min-h-[80px]" placeholder="驳回原因（必填）"></textarea>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeReject">取消</button>
          <button class="btn-danger" :disabled="rejectSaving" @click="submitReject">
            {{ rejectSaving ? '提交中…' : '确认驳回' }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { useUserStore } from '../../stores/user'
import { formatDate, formatMoney, formatNumber, useDebounce } from '../../composables/useDomainResource'
import SectionCard from '../../components/platform/SectionCard.vue'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['go', 'changed'])

const api = apiFor('marketplace')
const app = useAppStore()
const userStore = useUserStore()

const SECTIONS = [
  { key: 'publishers', label: '发布者' },
  { key: 'apps', label: '应用管理' },
  { key: 'revenue', label: '收入概览' },
]
const TYPE_OPTIONS = [
  { value: 'app', label: '应用' },
  { value: 'plugin', label: '插件' },
  { value: 'integration', label: '集成' },
  { value: 'template', label: '模板' },
  { value: 'theme', label: '主题' },
]

const section = ref('publishers')
const { value: q, debounced: debouncedQ } = useDebounce(320)

const publishers = ref([])
const publisherTotal = ref(0)
const publisherPage = ref(1)
const publisherPageSize = ref(12)
const publisherPages = computed(() =>
  Math.max(1, Math.ceil(publisherTotal.value / Math.max(1, publisherPageSize.value)))
)
const status = ref('')
const loading = ref(false)
const publisherError = ref('')
const myPublishers = ref([])
const myLoading = ref(false)

const activePublisherId = ref('')
const activePublisher = computed(() =>
  myPublishers.value.find((row) => String(row.id) === String(activePublisherId.value)) || null
)

const apps = ref([])
const appStatus = ref('')
const appLoading = ref(false)
const appError = ref('')
const categories = ref([])

const revenueData = ref(null)
const revenueLoading = ref(false)
const revenueError = ref('')
const settlementForm = reactive({
  bank_name: '',
  account_name: '',
  account_no: '',
  cycle: '',
  tax_no: '',
  contact: '',
})
const settlementSaving = ref(false)

const publisherCreateOpen = ref(false)
const publisherSaving = ref(false)
const publisherForm = reactive({ name: '', slug: '', summary: '', website: '', contact_email: '' })

const publisherDetailOpen = ref(false)
const publisherDetail = ref(null)

const suspendOpen = ref(false)
const suspendTarget = ref(null)
const suspendReason = ref('')
const suspendSaving = ref(false)

const appCreateOpen = ref(false)
const appSaving = ref(false)
const appForm = reactive({
  name: '',
  code: '',
  summary: '',
  description: '',
  type: 'app',
  category_id: '',
  pricing_mode: 'free',
  tags: '',
  icon: '',
})

const versionsOpen = ref(false)
const versionTarget = ref(null)
const versions = ref([])
const versionsLoading = ref(false)
const versionsError = ref('')
const versionSaving = ref(false)
const versionForm = reactive({
  version: '',
  min_platform_version: '3.0.0',
  package_size: 0,
  changelog: '',
  breaking: false,
})

const rejectOpen = ref(false)
const rejectTarget = ref(null)
const rejectReason = ref('')
const rejectSaving = ref(false)

const fmtNum = (value) => formatNumber(value)
const fmtDate = (value, withTime = false) => formatDate(value, withTime)
const fmtMoney = (value, currency = 'CNY') => formatMoney(value, currency)
const fmtPct = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(1)}%`
}
const fmtRating = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

const verifiedCount = computed(() => publishers.value.filter((row) => row.status === 'verified').length)
const pendingCount = computed(() => publishers.value.filter((row) => row.status === 'pending').length)
const publishedAppCount = computed(() => apps.value.filter((row) => row.status === 'published').length)
const reviewingAppCount = computed(() => apps.value.filter((row) => row.status === 'reviewing').length)

const revenueCurrencyRows = computed(() => {
  const map = revenueData.value?.revenue?.by_currency || {}
  return Object.entries(map).map(([currency, row]) => ({ currency, ...row }))
})

const revenueKpis = computed(() => {
  const revenue = revenueData.value?.revenue || {}
  return [
    { key: 'gross', label: '成交流水', value: fmtMoney(revenue.gross), hint: `订单 ${fmtNum(revenue.orders)} 单，原币合计`, icon: '¥' },
    { key: 'refund', label: '退款冲减', value: fmtMoney(revenue.refund), hint: `退款订单 ${fmtNum(revenue.refunded_orders)} 单`, icon: '↺' },
    { key: 'net', label: '发布者净收入', value: fmtMoney(revenue.publisher_net_cny), hint: `分成 ${fmtPct(revenue.share_pct)}，折算人民币`, icon: '◈' },
    { key: 'fee', label: '平台抽成', value: fmtMoney(revenue.platform_fee), hint: '按原币合计', icon: '▤' },
  ]
})

function publisherLabel(value) {
  const map = { pending: '待认证', verified: '已认证', suspended: '已暂停' }
  return map[value] || value || '未知'
}

function publisherClass(value) {
  const map = {
    pending: 'bg-amber-50 text-amber-600',
    verified: 'bg-emerald-50 text-emerald-600',
    suspended: 'bg-rose-50 text-rose-600',
  }
  return map[value] || ''
}

function listingLabel(value) {
  const map = { draft: '草稿', reviewing: '审核中', published: '已上架', suspended: '已暂停', delisted: '已下架' }
  return map[value] || value || '未知'
}

function listingClass(value) {
  const map = {
    draft: 'bg-ink-100 text-ink-500',
    reviewing: 'bg-amber-50 text-amber-600',
    published: 'bg-emerald-50 text-emerald-600',
    suspended: 'bg-rose-50 text-rose-600',
    delisted: 'bg-ink-100 text-ink-500',
  }
  return map[value] || ''
}

function versionLabel(value) {
  const map = { draft: '草稿', published: '已发布', delisted: '已下架' }
  return map[value] || value || '未知'
}

function versionClass(value) {
  const map = {
    draft: 'bg-amber-50 text-amber-600',
    published: 'bg-emerald-50 text-emerald-600',
    delisted: 'bg-ink-100 text-ink-500',
  }
  return map[value] || ''
}

async function loadPublishers() {
  if (!api) {
    publisherError.value = '应用市场接口不可用'
    return
  }
  loading.value = true
  publisherError.value = ''
  try {
    const data = await api.list('publishers/', {
      page: publisherPage.value,
      page_size: publisherPageSize.value,
      q: debouncedQ.value.trim() || undefined,
      status: status.value || undefined,
    })
    publishers.value = data.items || []
    publisherTotal.value = Number(data.count) || 0
    publisherPage.value = Number(data.page) || publisherPage.value
  } catch (e) {
    publishers.value = []
    publisherTotal.value = 0
    publisherError.value = e?.message || '发布者加载失败'
    app.toastMsg(publisherError.value, 'error')
  } finally {
    loading.value = false
  }
}

async function loadMyPublishers() {
  myLoading.value = true
  try {
    const data = await api.list('publishers/mine/', { page: 1, page_size: 100 })
    myPublishers.value = data.items || []
    const exists = myPublishers.value.some((row) => String(row.id) === String(activePublisherId.value))
    if (!exists) {
      activePublisherId.value = myPublishers.value.length ? String(myPublishers.value[0].id) : ''
    }
  } catch (e) {
    myPublishers.value = []
    app.toastMsg(e?.message || '我的发布者加载失败', 'info')
  } finally {
    myLoading.value = false
  }
}

async function loadCategories() {
  try {
    const data = await api.list('categories/', { page: 1, page_size: 100, status: 'active' })
    categories.value = data.items || []
  } catch (e) {
    categories.value = []
  }
}

function resetPublisherFilters() {
  q.value = ''
  debouncedQ.value = ''
  status.value = ''
  publisherPage.value = 1
  loadPublishers()
}

function goPublisherPage(next) {
  const target = Math.min(Math.max(1, Number(next) || 1), publisherPages.value)
  if (target === publisherPage.value) return
  publisherPage.value = target
  loadPublishers()
}

async function loadApps() {
  if (!activePublisherId.value) {
    apps.value = []
    appError.value = ''
    return
  }
  appLoading.value = true
  appError.value = ''
  try {
    const data = await api.list('listings/mine/', {
      page: 1,
      page_size: 100,
      publisher_id: activePublisherId.value,
      status: appStatus.value || undefined,
    })
    apps.value = data.items || []
  } catch (e) {
    apps.value = []
    appError.value = e?.message || '应用列表加载失败'
    app.toastMsg(appError.value, 'error')
  } finally {
    appLoading.value = false
  }
}

async function loadRevenue() {
  if (!activePublisherId.value) {
    revenueData.value = null
    revenueError.value = ''
    return
  }
  revenueLoading.value = true
  revenueError.value = ''
  try {
    const [overview, detail] = await Promise.all([
      api.get(`publishers/${activePublisherId.value}/overview/`),
      api.get(`publishers/${activePublisherId.value}/`),
    ])
    revenueData.value = overview
    const info = detail?.settlement_info || {}
    settlementForm.bank_name = info.bank_name || ''
    settlementForm.account_name = info.account_name || ''
    settlementForm.account_no = info.account_no || ''
    settlementForm.cycle = info.cycle || ''
    settlementForm.tax_no = info.tax_no || ''
    settlementForm.contact = info.contact || ''
  } catch (e) {
    revenueData.value = null
    revenueError.value = e?.message || '经营数据加载失败（仅所有者或管理员可查看）'
    app.toastMsg(revenueError.value, 'info')
  } finally {
    revenueLoading.value = false
  }
}

async function reloadCurrent() {
  if (section.value === 'publishers') {
    await Promise.all([loadPublishers(), loadMyPublishers()])
  } else if (section.value === 'apps') {
    await Promise.all([loadMyPublishers(), loadApps()])
  } else {
    await Promise.all([loadMyPublishers(), loadRevenue()])
  }
}

function openPublisherCreate() {
  publisherForm.name = ''
  publisherForm.slug = ''
  publisherForm.summary = ''
  publisherForm.website = ''
  publisherForm.contact_email = ''
  publisherCreateOpen.value = true
}

function closePublisherCreate() {
  publisherCreateOpen.value = false
  publisherSaving.value = false
}

async function createPublisher() {
  const name = publisherForm.name.trim()
  if (!name) {
    app.toastMsg('请输入发布者名称', 'info')
    return
  }
  publisherSaving.value = true
  try {
    await api.post('publishers/', {
      name,
      slug: publisherForm.slug.trim() || undefined,
      summary: publisherForm.summary.trim(),
      website: publisherForm.website.trim(),
      contact_email: publisherForm.contact_email.trim(),
    })
    app.toastMsg('发布者申请已提交，等待认证', 'success')
    closePublisherCreate()
    await Promise.all([loadPublishers(), loadMyPublishers()])
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '申请提交失败', 'error')
  } finally {
    publisherSaving.value = false
  }
}

async function openPublisherDetail(row) {
  publisherDetailOpen.value = true
  publisherDetail.value = row
  try {
    publisherDetail.value = await api.get(`publishers/${row.id}/`)
  } catch (e) {
    app.toastMsg(e?.message || '发布者详情加载失败', 'error')
  }
}

async function verifyPublisher(row) {
  try {
    await api.post(`publishers/${row.id}/verify/`)
    app.toastMsg('发布者已认证', 'success')
    await Promise.all([loadPublishers(), loadMyPublishers()])
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '认证失败', 'error')
  }
}

function openSuspend(row) {
  suspendTarget.value = row
  suspendReason.value = ''
  suspendOpen.value = true
}

function closeSuspend() {
  suspendOpen.value = false
  suspendTarget.value = null
  suspendReason.value = ''
  suspendSaving.value = false
}

async function submitSuspend() {
  if (!suspendTarget.value) return
  const reason = suspendReason.value.trim()
  if (!reason) {
    app.toastMsg('请填写暂停原因', 'info')
    return
  }
  suspendSaving.value = true
  try {
    await api.post(`publishers/${suspendTarget.value.id}/suspend/`, { reason })
    app.toastMsg('发布者已暂停，关联应用同步暂停', 'success')
    closeSuspend()
    await Promise.all([loadPublishers(), loadMyPublishers(), loadApps()])
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '暂停失败', 'error')
  } finally {
    suspendSaving.value = false
  }
}

function usePublisher(row) {
  activePublisherId.value = String(row.id)
  section.value = 'revenue'
  loadRevenue()
}

function openAppCreate() {
  if (!activePublisherId.value) {
    app.toastMsg('请先选择发布者', 'info')
    return
  }
  appForm.name = ''
  appForm.code = ''
  appForm.summary = ''
  appForm.description = ''
  appForm.type = 'app'
  appForm.category_id = ''
  appForm.pricing_mode = 'free'
  appForm.tags = ''
  appForm.icon = ''
  appCreateOpen.value = true
}

function closeAppCreate() {
  appCreateOpen.value = false
  appSaving.value = false
}

async function createApp() {
  const name = appForm.name.trim()
  if (!name) {
    app.toastMsg('请输入应用名称', 'info')
    return
  }
  appSaving.value = true
  try {
    await api.post('listings/', {
      publisher_id: Number(activePublisherId.value),
      code: appForm.code.trim() || undefined,
      name,
      summary: appForm.summary.trim(),
      description: appForm.description.trim(),
      icon: appForm.icon.trim(),
      type: appForm.type,
      category_id: appForm.category_id ? Number(appForm.category_id) : undefined,
      pricing_mode: appForm.pricing_mode,
      tags: appForm.tags,
    })
    app.toastMsg('应用草稿已创建', 'success')
    closeAppCreate()
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '创建应用失败', 'error')
  } finally {
    appSaving.value = false
  }
}

async function openVersions(row) {
  versionTarget.value = row
  versionsOpen.value = true
  versions.value = []
  versionsError.value = ''
  versionForm.version = ''
  versionForm.min_platform_version = row.latest_version?.min_platform_version || '3.0.0'
  versionForm.package_size = 0
  versionForm.changelog = ''
  versionForm.breaking = false
  await loadVersions(row)
}

function closeVersions() {
  versionsOpen.value = false
  versionTarget.value = null
  versions.value = []
  versionsError.value = ''
  versionSaving.value = false
}

async function loadVersions(row) {
  if (!row) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const data = await api.list(`listings/${row.id}/versions/`, { page: 1, page_size: 100 })
    versions.value = data.items || []
  } catch (e) {
    versions.value = []
    versionsError.value = e?.message || '版本加载失败'
    app.toastMsg(versionsError.value, 'error')
  } finally {
    versionsLoading.value = false
  }
}

async function createVersion() {
  if (!versionTarget.value) return
  const versionText = versionForm.version.trim()
  if (!versionText) {
    app.toastMsg('请输入版本号', 'info')
    return
  }
  versionSaving.value = true
  try {
    await api.post(`listings/${versionTarget.value.id}/versions/`, {
      version: versionText,
      changelog: versionForm.changelog.trim(),
      min_platform_version: versionForm.min_platform_version.trim() || '3.0.0',
      package_size: Number(versionForm.package_size) || 0,
      breaking: Boolean(versionForm.breaking),
    })
    app.toastMsg('版本草稿已创建', 'success')
    versionForm.version = ''
    versionForm.changelog = ''
    versionForm.breaking = false
    await loadVersions(versionTarget.value)
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '创建版本失败', 'error')
  } finally {
    versionSaving.value = false
  }
}

async function publishVersion(row) {
  try {
    await api.post(`versions/${row.id}/publish/`)
    app.toastMsg('版本已发布', 'success')
    await loadVersions(versionTarget.value)
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '版本发布失败', 'error')
  }
}

async function submitListing(row) {
  try {
    await api.post(`listings/${row.id}/submit/`)
    app.toastMsg('已提交审核', 'success')
    await loadApps()
    if (versionTarget.value?.id === row.id) {
      versionTarget.value = { ...versionTarget.value, status: 'reviewing' }
    }
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '提交审核失败', 'error')
  }
}

async function withdrawListing(row) {
  try {
    await api.post(`listings/${row.id}/withdraw/`)
    app.toastMsg('已撤回审核', 'success')
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '撤回失败', 'error')
  }
}

async function publishListing(row) {
  try {
    await api.post(`listings/${row.id}/publish/`)
    app.toastMsg('应用已上架', 'success')
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '上架失败', 'error')
  }
}

async function delistListing(row) {
  try {
    await api.post(`listings/${row.id}/delist/`)
    app.toastMsg('应用已下架', 'success')
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '下架失败', 'error')
  }
}

async function approveListing(row) {
  try {
    await api.post(`listings/${row.id}/approve/`)
    app.toastMsg('审核通过并上架', 'success')
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '审核失败', 'error')
  }
}

function openReject(row) {
  rejectTarget.value = row
  rejectReason.value = ''
  rejectOpen.value = true
}

function closeReject() {
  rejectOpen.value = false
  rejectTarget.value = null
  rejectReason.value = ''
  rejectSaving.value = false
}

async function submitReject() {
  if (!rejectTarget.value) return
  const reason = rejectReason.value.trim()
  if (!reason) {
    app.toastMsg('请填写驳回原因', 'info')
    return
  }
  rejectSaving.value = true
  try {
    await api.post(`listings/${rejectTarget.value.id}/reject/`, { reason })
    app.toastMsg('已驳回', 'success')
    closeReject()
    await loadApps()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '驳回失败', 'error')
  } finally {
    rejectSaving.value = false
  }
}

async function saveSettlement() {
  if (!activePublisherId.value) return
  const info = {
    bank_name: settlementForm.bank_name.trim(),
    account_name: settlementForm.account_name.trim(),
    account_no: settlementForm.account_no.trim(),
    cycle: settlementForm.cycle.trim(),
    tax_no: settlementForm.tax_no.trim(),
    contact: settlementForm.contact.trim(),
  }
  if (!info.bank_name && !info.account_name && !info.account_no) {
    app.toastMsg('至少填写银行名称、账户名称或账号之一', 'info')
    return
  }
  settlementSaving.value = true
  try {
    await api.post(`publishers/${activePublisherId.value}/settlement/`, { settlement_info: info })
    app.toastMsg('结算信息已保存', 'success')
    await loadRevenue()
  } catch (e) {
    app.toastMsg(e?.message || '结算信息保存失败', 'error')
  } finally {
    settlementSaving.value = false
  }
}

watch([debouncedQ, status], () => {
  publisherPage.value = 1
  loadPublishers()
})

watch(appStatus, () => loadApps())

watch(activePublisherId, (value) => {
  if (!value) return
  if (section.value === 'apps') loadApps()
  if (section.value === 'revenue') loadRevenue()
})

watch(section, (value) => {
  if (value === 'publishers') loadPublishers()
  else if (value === 'apps') loadApps()
  else loadRevenue()
})

watch(
  () => props.refreshKey,
  () => reloadCurrent()
)

onMounted(() => {
  loadPublishers()
  loadMyPublishers()
  loadCategories()
})
</script>