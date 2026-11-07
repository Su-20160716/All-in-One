<template>
  <div class="space-y-3">
    <div class="card space-y-2 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="q"
          class="input w-full sm:w-[240px]"
          placeholder="搜索应用名称、标签或简介"
          aria-label="搜索应用"
        />
        <select v-model="categoryId" class="input w-[150px] py-1" aria-label="按分类筛选">
          <option value="">全部分类</option>
          <option v-for="cat in categories" :key="cat.id" :value="String(cat.id)">
            {{ cat.name }}（{{ cat.listing_count || 0 }}）
          </option>
        </select>
        <select v-model="pricingMode" class="input w-[130px] py-1" aria-label="按价格筛选">
          <option value="">全部价格</option>
          <option value="free">免费</option>
          <option value="paid">付费</option>
          <option value="freemium">免费增值</option>
        </select>
        <select v-model="sort" class="input w-[130px] py-1" aria-label="排序方式">
          <option value="relevance">相关度</option>
          <option value="rating">评分优先</option>
          <option value="installs">安装量优先</option>
          <option value="newest">最新上架</option>
          <option value="price">价格从低到高</option>
          <option value="featured">推荐位优先</option>
        </select>

        <div class="ml-auto flex items-center gap-1">
          <button
            class="rounded-control px-2 py-1 text-[12px]"
            :class="viewMode === 'card' ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 border border-ink-200'"
            @click="viewMode = 'card'"
          >
            卡片
          </button>
          <button
            class="rounded-control px-2 py-1 text-[12px]"
            :class="viewMode === 'table' ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 border border-ink-200'"
            @click="viewMode = 'table'"
          >
            表格
          </button>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span class="tag">共 {{ fmtNum(total) }} 个应用</span>
        <span v-if="loading" class="tag">加载中</span>
        <span v-if="q" class="tag">关键词：{{ q }}</span>
        <span v-if="categoryName" class="tag">分类：{{ categoryName }}</span>
        <button class="btn-ghost py-1 text-[11px]" :disabled="loading" @click="resetFilters">清除筛选</button>
        <button class="btn-outline ml-auto py-1 text-[11px]" :disabled="loading" @click="loadListings">
          {{ loading ? '刷新中…' : '刷新目录' }}
        </button>
      </div>
    </div>

    <div
      v-if="error"
      class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1 truncate">{{ error }}</span>
      <button class="shrink-0 font-medium" @click="loadListings">重试</button>
    </div>

    <div v-else-if="loading && !items.length" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <div v-for="n in 6" :key="n" class="card space-y-2 p-4">
        <div class="h-10 w-10 animate-pulse rounded-control bg-ink-100"></div>
        <div class="h-4 w-2/3 animate-pulse rounded bg-ink-100"></div>
        <div class="h-3 w-full animate-pulse rounded bg-ink-50"></div>
        <div class="h-3 w-4/5 animate-pulse rounded bg-ink-50"></div>
      </div>
    </div>

    <div
      v-else-if="!items.length"
      class="card rounded-control border-dashed py-14 text-center text-[12px] text-ink-400"
    >
      没有符合条件的应用，尝试调整关键词或筛选条件
    </div>

    <div v-else-if="viewMode === 'card'" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="item in items"
        :key="item.id"
        class="card flex flex-col gap-2 p-4 transition-colors hover:border-brand-300"
      >
        <div class="flex items-start gap-2.5">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-brand-50 text-[15px] font-semibold text-brand-700">
            {{ (item.name || '应').slice(0, 1) }}
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5">
              <button class="min-w-0 truncate text-[14px] font-semibold text-ink-900 hover:text-brand-600" @click="openDetail(item)">
                {{ item.name }}
              </button>
              <span v-if="item.featured" class="tag bg-amber-50 text-amber-700">推荐</span>
            </div>
            <div class="truncate text-[11px] text-ink-400">{{ item.publisher?.name || '未知发布者' }} · {{ item.category?.name || '未分类' }}</div>
          </div>
          <span class="tag shrink-0" :class="listingClass(item.status)">{{ listingLabel(item.status) }}</span>
        </div>

        <p class="line-clamp-2 min-h-[32px] text-[12px] leading-relaxed text-ink-500">
          {{ item.summary || '该应用暂未填写简介' }}
        </p>

        <div class="flex flex-wrap items-center gap-1.5">
          <span v-for="tag in (item.tags || []).slice(0, 3)" :key="tag" class="tag">{{ tag }}</span>
          <span class="tag">{{ typeLabel(item.type) }}</span>
          <span class="tag" :class="item.pricing_mode === 'free' ? 'bg-emerald-50 text-emerald-600' : ''">
            {{ priceLabel(item) }}
          </span>
        </div>

        <div class="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-ink-50 pt-2 text-[11px] text-ink-400">
          <span>{{ fmtRating(item.rating) }} 分 · {{ fmtNum(item.rating_count) }} 条评价</span>
          <span>安装 {{ fmtNum(item.install_count) }}</span>
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <button class="btn-outline py-1 text-[12px]" @click="openDetail(item)">详情</button>
          <button
            v-if="!installOf(item)"
            class="btn-primary py-1 text-[12px]"
            @click="openInstall(item)"
          >
            安装
          </button>
          <template v-else>
            <span class="tag" :class="installClass(installOf(item).status)">{{ installLabel(installOf(item).status) }}</span>
            <button
              v-if="installOf(item).status === 'installed'"
              class="btn-ghost py-1 text-[12px]"
              @click="askToggle(installOf(item), false)"
            >
              停用
            </button>
            <button
              v-else-if="installOf(item).status === 'disabled'"
              class="btn-ghost py-1 text-[12px]"
              @click="askToggle(installOf(item), true)"
            >
              启用
            </button>
            <button class="btn-ghost py-1 text-[12px] text-rose-600" @click="askUninstall(installOf(item))">卸载</button>
          </template>
          <button class="btn-ghost ml-auto py-1 text-[11px]" @click="openReport(item)">举报</button>
        </div>
      </article>
    </div>

    <div v-else class="card overflow-x-auto">
      <table class="w-full min-w-[900px]">
        <thead class="border-b border-ink-100 bg-ink-50/60">
          <tr>
            <th class="th">应用</th>
            <th class="th">分类</th>
            <th class="th">价格</th>
            <th class="th text-right">评分</th>
            <th class="th text-right">安装量</th>
            <th class="th">发布者</th>
            <th class="th">状态</th>
            <th class="th text-right">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-ink-50">
          <tr v-for="item in items" :key="item.id" class="hover:bg-ink-50/40">
            <td class="td">
              <button class="block max-w-[240px] truncate text-left font-medium text-ink-800 hover:text-brand-600" @click="openDetail(item)">
                {{ item.name }}
              </button>
              <div class="max-w-[240px] truncate text-[11px] text-ink-400">{{ item.code }}</div>
            </td>
            <td class="td">{{ item.category?.name || '未分类' }}</td>
            <td class="td">{{ priceLabel(item) }}</td>
            <td class="td text-right">{{ fmtRating(item.rating) }}（{{ fmtNum(item.rating_count) }}）</td>
            <td class="td text-right">{{ fmtNum(item.install_count) }}</td>
            <td class="td max-w-[160px] truncate">{{ item.publisher?.name || '—' }}</td>
            <td class="td">
              <span class="tag" :class="listingClass(item.status)">{{ listingLabel(item.status) }}</span>
            </td>
            <td class="td text-right">
              <div class="flex flex-wrap justify-end gap-1">
                <button class="btn-ghost py-0.5 text-[11px]" @click="openDetail(item)">详情</button>
                <button
                  v-if="!installOf(item)"
                  class="btn-primary px-2 py-0.5 text-[11px]"
                  @click="openInstall(item)"
                >
                  安装
                </button>
                <button v-else class="tag" :class="installClass(installOf(item).status)" @click="openInstall(item)">
                  {{ installLabel(installOf(item).status) }}
                </button>
                <button class="btn-ghost py-0.5 text-[11px] text-rose-600" @click="openReport(item)">举报</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="total > 0" class="flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-500">
      <span>第 {{ page }} / {{ pages }} 页 · 共 {{ fmtNum(total) }} 个应用</span>
      <div class="flex items-center gap-1.5">
        <button class="btn-outline py-1 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
        <button class="btn-outline py-1 text-[12px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="detailOpen" class="fixed inset-0 z-[95] flex justify-end">
        <div class="absolute inset-0 bg-ink-900/40" @click="closeDetail"></div>
        <aside class="relative z-10 flex h-full w-full max-w-[620px] flex-col bg-white shadow-pop">
          <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="tag" :class="listingClass(detail?.status)">{{ listingLabel(detail?.status) }}</span>
                <span class="tag">{{ typeLabel(detail?.type) }}</span>
                <span class="tag">{{ priceLabel(detail) }}</span>
                <span v-if="detail?.featured" class="tag bg-amber-50 text-amber-700">推荐位</span>
              </div>
              <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">{{ detail?.name || '应用详情' }}</h3>
              <p class="truncate text-[11px] text-ink-400">{{ detail?.code }} · {{ detail?.publisher?.name || '未知发布者' }}</p>
            </div>
            <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" @click="closeDetail">✕</button>
          </div>

          <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
            <div v-if="detailLoading" class="py-10 text-center text-[12px] text-ink-400">详情加载中…</div>
            <div v-else-if="detailError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
              <span class="min-w-0 flex-1">{{ detailError }}</span>
              <button class="shrink-0 font-medium" @click="loadDetail(detail?.id)">重试</button>
            </div>
            <template v-else-if="detail">
              <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
                <div class="text-ink-400">分类</div>
                <div class="text-ink-700">{{ detail.category?.name || '未分类' }}</div>
                <div class="text-ink-400">最新版本</div>
                <div class="text-ink-700">{{ detail.latest_version?.version || '暂无已发布版本' }}</div>
                <div class="text-ink-400">平台下限</div>
                <div class="text-ink-700">{{ detail.latest_version?.min_platform_version || '未声明' }}</div>
                <div class="text-ink-400">安装量</div>
                <div class="text-ink-700">{{ fmtNum(detail.install_count) }}</div>
                <div class="text-ink-400">评分</div>
                <div class="text-ink-700">{{ fmtRating(detail.rating) }} 分（{{ fmtNum(detail.rating_count) }} 条）</div>
                <div class="text-ink-400">上架时间</div>
                <div class="text-ink-700">{{ fmtDate(detail.published_at) }}</div>
                <div class="text-ink-400">当前安装</div>
                <div class="text-ink-700">
                  <span v-if="installOf(detail)">{{ installLabel(installOf(detail).status) }} · {{ installOf(detail).version?.version || '未记录' }}</span>
                  <span v-else>未安装</span>
                </div>
              </div>

              <div class="flex flex-wrap gap-1.5">
                <span v-for="tag in detail.tags || []" :key="tag" class="tag">{{ tag }}</span>
              </div>

              <div>
                <div class="mb-1 text-[13px] font-medium text-ink-700">应用简介</div>
                <p class="whitespace-pre-line text-[12px] leading-relaxed text-ink-600">
                  {{ detail.description || detail.summary || '该应用暂未填写详细介绍' }}
                </p>
              </div>

              <div>
                <div class="mb-1.5 flex items-center justify-between">
                  <span class="text-[13px] font-medium text-ink-700">应用截图</span>
                  <span class="tag">{{ (detail.screenshots || []).length }} 张</span>
                </div>
                <div v-if="!(detail.screenshots || []).length" class="rounded-control border border-dashed border-ink-200 py-6 text-center text-[12px] text-ink-400">
                  暂无截图
                </div>
                <div v-else class="flex gap-2 overflow-x-auto pb-1">
                  <figure v-for="shot in detail.screenshots" :key="shot.id" class="w-40 shrink-0">
                    <img
                      :src="shot.file_url"
                      :alt="shot.caption || '应用截图'"
                      class="h-24 w-full rounded-control border border-ink-100 object-cover"
                      loading="lazy"
                    />
                    <figcaption class="mt-1 truncate text-[11px] text-ink-400">{{ shot.caption || shot.file_name }}</figcaption>
                  </figure>
                </div>
              </div>

              <div>
                <div class="mb-1.5 flex items-center justify-between">
                  <span class="text-[13px] font-medium text-ink-700">版本列表</span>
                  <span class="tag">{{ (detail.versions || []).length }} 个已发布版本</span>
                </div>
                <div v-if="!(detail.versions || []).length" class="rounded-control border border-dashed border-ink-200 py-6 text-center text-[12px] text-ink-400">
                  暂无已发布版本
                </div>
                <div v-else class="divide-y divide-ink-50">
                  <div v-for="ver in detail.versions" :key="ver.id" class="flex flex-wrap items-center gap-2 py-1.5 text-[12px]">
                    <span class="font-mono text-ink-800">{{ ver.version }}</span>
                    <span v-if="ver.breaking" class="tag bg-rose-50 text-rose-600">破坏性变更</span>
                    <span class="text-ink-400">平台 ≥ {{ ver.min_platform_version }}</span>
                    <span class="ml-auto text-ink-400">{{ fmtDate(ver.published_at) }}</span>
                  </div>
                </div>
              </div>

              <div>
                <div class="mb-1.5 flex items-center justify-between">
                  <span class="text-[13px] font-medium text-ink-700">兼容性</span>
                  <span class="tag">{{ (detail.compatibility || []).length }} 条</span>
                </div>
                <div v-if="!(detail.compatibility || []).length" class="rounded-control border border-dashed border-ink-200 py-5 text-center text-[12px] text-ink-400">
                  暂无兼容性标签
                </div>
                <div v-else class="flex flex-wrap gap-1.5">
                  <span v-for="row in detail.compatibility" :key="row.id" class="tag" :title="row.note">
                    {{ row.platform_version }} · {{ row.tag }}
                  </span>
                </div>
              </div>

              <div class="border-t border-ink-100 pt-3">
                <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <span class="text-[13px] font-medium text-ink-700">评价</span>
                  <span class="text-[11px] text-ink-400">
                    {{ fmtRating(reviewSummary?.rating ?? detail.rating) }} 分 · {{ fmtNum(reviewSummary?.rating_count ?? detail.rating_count) }} 条已发布
                  </span>
                </div>
                <div class="mb-2 flex flex-wrap gap-1.5">
                  <span v-for="star in STAR_KEYS" :key="star" class="tag">
                    {{ star }} 星 {{ fmtNum(reviewSummary?.distribution?.[star]) }}
                  </span>
                </div>

                <div v-if="reviewError" class="mb-2 rounded-control bg-rose-50 px-2 py-1.5 text-[11px] text-rose-600">
                  {{ reviewError }}
                </div>
                <div v-else-if="reviewLoading && !reviews.length" class="py-4 text-center text-[12px] text-ink-400">评价加载中…</div>
                <div v-else-if="!reviews.length" class="rounded-control border border-dashed border-ink-200 py-5 text-center text-[12px] text-ink-400">
                  还没有评价，欢迎发表第一条
                </div>
                <div v-else class="space-y-2">
                  <article v-for="row in reviews" :key="row.id" class="rounded-control border border-ink-100 px-3 py-2">
                    <div class="flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
                      <span class="font-medium text-ink-700">{{ row.owner?.nickname || row.owner?.username || '匿名用户' }}</span>
                      <span>{{ row.rating }} 分</span>
                      <span v-if="row.verified_purchase" class="tag bg-emerald-50 text-emerald-600">已购买</span>
                      <span v-if="row.status !== 'published'" class="tag bg-amber-50 text-amber-600">{{ reviewLabel(row.status) }}</span>
                      <span class="ml-auto">{{ fmtDate(row.created_at, true) }}</span>
                    </div>
                    <div v-if="row.title" class="mt-1 text-[13px] font-medium text-ink-800">{{ row.title }}</div>
                    <p class="mt-0.5 whitespace-pre-line text-[12px] leading-relaxed text-ink-600">{{ row.content || '（无文字内容）' }}</p>
                    <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <button class="btn-ghost px-1.5 py-0.5 text-[11px]" @click="toggleHelpful(row)">
                        有用 {{ fmtNum(row.helpful_count) }}
                      </button>
                      <button class="btn-ghost px-1.5 py-0.5 text-[11px]" @click="toggleReplies(row)">
                        {{ repliesMap[row.id] ? '收起回复' : `回复 ${row.reply_count || 0}` }}
                      </button>
                    </div>
                    <div v-if="repliesMap[row.id]" class="mt-1.5 space-y-1 border-l-2 border-ink-100 pl-2">
                      <div v-if="repliesLoading[row.id]" class="text-[11px] text-ink-400">回复加载中…</div>
                      <div
                        v-for="reply in repliesMap[row.id]"
                        :key="reply.id"
                        class="text-[11px] leading-relaxed text-ink-500"
                      >
                        <span class="font-medium text-ink-700">{{ reply.owner?.nickname || reply.owner?.username || '用户' }}</span>
                        ：{{ reply.content }}
                      </div>
                      <div v-if="!repliesLoading[row.id] && !repliesMap[row.id].length" class="text-[11px] text-ink-400">暂无回复</div>
                      <div class="flex items-center gap-1.5 pt-1">
                        <input
                          v-model="replyDraft[row.id]"
                          class="input py-1 text-[11px]"
                          placeholder="回复该评价"
                          @keyup.enter="submitReply(row)"
                        />
                        <button class="btn-primary px-2 py-0.5 text-[11px]" :disabled="replySaving === row.id" @click="submitReply(row)">
                          {{ replySaving === row.id ? '发送中' : '发送' }}
                        </button>
                      </div>
                    </div>
                  </article>
                  <button
                    v-if="reviews.length < reviewTotal"
                    class="btn-ghost w-full py-1 text-[12px]"
                    :disabled="reviewLoading"
                    @click="loadReviews(false)"
                  >
                    {{ reviewLoading ? '加载中…' : '加载更多评价' }}
                  </button>
                </div>

                <div class="mt-3 rounded-control bg-ink-50/60 p-3">
                  <div class="mb-1.5 text-[12px] font-medium text-ink-700">发表评价</div>
                  <div class="flex flex-wrap items-center gap-2">
                    <label class="flex items-center gap-1 text-[12px] text-ink-500">
                      评分
                      <select v-model.number="reviewForm.rating" class="input w-16 py-1">
                        <option v-for="n in 5" :key="n" :value="n">{{ n }}</option>
                      </select>
                    </label>
                    <input v-model="reviewForm.title" class="input flex-1 py-1" maxlength="200" placeholder="评价标题（可选）" />
                  </div>
                  <textarea
                    v-model="reviewForm.content"
                    class="input mt-2 min-h-[64px] py-1"
                    placeholder="写下你的使用体验，提交后进入待审状态"
                  ></textarea>
                  <div class="mt-2 flex justify-end">
                    <button class="btn-primary py-1 text-[12px]" :disabled="reviewSubmitting" @click="submitReview">
                      {{ reviewSubmitting ? '提交中…' : '提交评价' }}
                    </button>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <div class="flex flex-wrap items-center gap-2 border-t border-ink-100 px-4 py-3">
            <button
              v-if="detail && !installOf(detail)"
              class="btn-primary py-1 text-[12px]"
              @click="openInstall(detail)"
            >
              安装应用
            </button>
            <template v-else-if="detail && installOf(detail)">
              <span class="tag" :class="installClass(installOf(detail).status)">{{ installLabel(installOf(detail).status) }}</span>
              <button
                v-if="installOf(detail).status === 'installed'"
                class="btn-outline py-1 text-[12px]"
                @click="askToggle(installOf(detail), false)"
              >
                停用
              </button>
              <button
                v-else-if="installOf(detail).status === 'disabled'"
                class="btn-outline py-1 text-[12px]"
                @click="askToggle(installOf(detail), true)"
              >
                启用
              </button>
              <button class="btn-danger py-1 text-[12px]" @click="askUninstall(installOf(detail))">卸载</button>
            </template>
            <button v-if="detail" class="btn-ghost ml-auto py-1 text-[12px]" @click="openReport(detail)">举报应用</button>
          </div>
        </aside>
      </div>
    </Teleport>

    <Modal :show="installOpen" title="安装应用" width="560px" @close="closeInstall">
      <div v-if="installTarget" class="space-y-3">
        <div class="rounded-control bg-ink-50/60 px-3 py-2">
          <div class="text-[13px] font-medium text-ink-800">{{ installTarget.name }}</div>
          <div class="text-[11px] text-ink-400">{{ installTarget.code }} · {{ priceLabel(installTarget) }}</div>
        </div>

        <div v-if="installVersionsLoading" class="py-4 text-center text-[12px] text-ink-400">版本加载中…</div>
        <div v-else-if="installVersionsError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ installVersionsError }}
        </div>
        <div v-else-if="!installVersions.length" class="rounded-control border border-dashed border-ink-200 py-4 text-center text-[12px] text-ink-400">
          该应用暂无已发布版本，暂时无法安装
        </div>
        <label v-else class="block text-[12px] text-ink-500">
          安装版本
          <select v-model="installVersionId" class="input mt-1">
            <option value="">由服务端解析最优兼容版本</option>
            <option v-for="ver in installVersions" :key="ver.id" :value="String(ver.id)">
              {{ ver.version }}（平台 ≥ {{ ver.min_platform_version }}）{{ ver.breaking ? ' · 破坏性变更' : '' }}
            </option>
          </select>
        </label>

        <div class="rounded-control border border-ink-100 px-3 py-2">
          <div class="mb-1 flex items-center gap-2 text-[12px] font-medium text-ink-700">
            兼容性预演
            <span v-if="installResolveLoading" class="tag">检查中</span>
            <span v-else-if="installResolve?.ok" class="tag bg-emerald-50 text-emerald-600">可以安装</span>
            <span v-else-if="installResolve" class="tag bg-rose-50 text-rose-600">存在冲突</span>
          </div>
          <div v-if="installResolveError" class="text-[11px] text-rose-600">{{ installResolveError }}</div>
          <template v-else-if="installResolve">
            <div class="text-[11px] text-ink-500">
              目标平台 {{ installResolve.platform_version || '默认版本' }} · 解析版本
              {{ installResolve.resolved?.version || installResolve.version || '由服务端决定' }}
            </div>
            <ul v-if="(installResolve.conflicts || []).length" class="mt-1 space-y-0.5">
              <li v-for="row in installResolve.conflicts" :key="row.code" class="text-[11px] text-rose-600">
                {{ row.code }}：{{ row.reason }}
              </li>
            </ul>
            <ul v-if="(installResolve.warnings || []).length" class="mt-1 space-y-0.5">
              <li v-for="(row, index) in installResolve.warnings" :key="index" class="text-[11px] text-amber-600">
                {{ row.message || row.reason || row }}
              </li>
            </ul>
          </template>
          <span v-else class="text-[11px] text-ink-400">安装前会由服务端做依赖与平台兼容解析</span>
        </div>

        <label class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="installForm.auto_update" type="checkbox" class="h-3.5 w-3.5" />
          允许自动更新
        </label>

        <label class="block text-[12px] text-ink-500">
          初始化配置（JSON 对象，可留空）
          <textarea v-model="installForm.config" class="input mt-1 min-h-[80px] font-mono text-[11px]"></textarea>
        </label>

        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeInstall">取消</button>
          <button
            class="btn-primary"
            :disabled="installSaving || installResolve?.ok === false || !installVersions.length"
            @click="submitInstall"
          >
            {{ installSaving ? '安装中…' : '确认安装' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="reportOpen" title="举报应用" width="480px" @close="closeReport">
      <div v-if="reportTarget" class="space-y-3">
        <div class="text-[12px] text-ink-500">举报对象：{{ reportTarget.name }}（{{ reportTarget.code }}）</div>
        <label class="block text-[12px] text-ink-500">
          举报原因
          <select v-model="reportForm.reason" class="input mt-1">
            <option v-for="row in REPORT_REASONS" :key="row.value" :value="row.value">{{ row.label }}</option>
          </select>
        </label>
        <label class="block text-[12px] text-ink-500">
          详细说明
          <textarea v-model="reportForm.detail" class="input mt-1 min-h-[80px]" placeholder="请描述问题，便于平台核实"></textarea>
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeReport">取消</button>
          <button class="btn-primary" :disabled="reportSaving" @click="submitReport">
            {{ reportSaving ? '提交中…' : '提交举报' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="confirmOpen" :title="confirmTitle" width="440px" @close="closeConfirm">
      <div class="space-y-3">
        <p class="text-[12px] leading-relaxed text-ink-600">{{ confirmText }}</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeConfirm">取消</button>
          <button class="btn-danger" :disabled="confirmBusy" @click="runConfirm">
            {{ confirmBusy ? '处理中…' : confirmLabel }}
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
import { useDebounce } from '../../composables/useDomainResource'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

const api = apiFor('marketplace')
const app = useAppStore()

const STAR_KEYS = ['5', '4', '3', '2', '1']
const REPORT_REASONS = [
  { value: 'malware', label: '恶意代码' },
  { value: 'copyright', label: '侵权' },
  { value: 'spam', label: '垃圾或误导' },
  { value: 'broken', label: '无法使用' },
  { value: 'other', label: '其他' },
]
const TYPE_LABELS = {
  app: '应用',
  plugin: '插件',
  integration: '集成',
  template: '模板',
  theme: '主题',
}

const { value: q, debounced: debouncedQ } = useDebounce(320)

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const loading = ref(false)
const error = ref('')
const viewMode = ref('card')
const categoryId = ref('')
const pricingMode = ref('')
const sort = ref('relevance')
const categories = ref([])
const installsMap = ref({})

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))
const categoryName = computed(() => {
  if (!categoryId.value) return ''
  const hit = categories.value.find((row) => String(row.id) === String(categoryId.value))
  return hit ? hit.name : ''
})

const detailOpen = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const reviews = ref([])
const reviewTotal = ref(0)
const reviewPage = ref(1)
const reviewLoading = ref(false)
const reviewError = ref('')
const reviewSummary = ref(null)
const reviewSubmitting = ref(false)
const reviewForm = reactive({ rating: 5, title: '', content: '' })
const repliesMap = reactive({})
const repliesLoading = reactive({})
const replyDraft = reactive({})
const replyTargetId = ref(0)
const replySaving = ref(0)

const installOpen = ref(false)
const installTarget = ref(null)
const installVersions = ref([])
const installVersionsLoading = ref(false)
const installVersionsError = ref('')
const installVersionId = ref('')
const installResolve = ref(null)
const installResolveLoading = ref(false)
const installResolveError = ref('')
const installSaving = ref(false)
const installForm = reactive({ auto_update: false, config: '' })

const reportOpen = ref(false)
const reportTarget = ref(null)
const reportSaving = ref(false)
const reportForm = reactive({ reason: 'spam', detail: '' })

const confirmOpen = ref(false)
const confirmTitle = ref('')
const confirmText = ref('')
const confirmLabel = ref('确认')
const confirmBusy = ref(false)
const confirmAction = ref(null)

const fmtNum = (value) => formatNumber(value)
const fmtDate = (value, withTime = false) => formatDate(value, withTime)
const fmtRating = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function typeLabel(value) {
  return TYPE_LABELS[value] || value || '应用'
}

function listingLabel(status) {
  const map = { draft: '草稿', reviewing: '审核中', published: '已上架', suspended: '已暂停', delisted: '已下架' }
  return map[status] || status || '未知'
}

function listingClass(status) {
  const map = {
    published: 'bg-emerald-50 text-emerald-600',
    reviewing: 'bg-amber-50 text-amber-600',
    draft: 'bg-ink-100 text-ink-500',
    suspended: 'bg-rose-50 text-rose-600',
    delisted: 'bg-ink-100 text-ink-500',
  }
  return map[status] || ''
}

function installLabel(status) {
  const map = { installed: '已安装', disabled: '已停用', uninstalled: '已卸载' }
  return map[status] || '未安装'
}

function installClass(status) {
  const map = {
    installed: 'bg-emerald-50 text-emerald-600',
    disabled: 'bg-amber-50 text-amber-600',
    uninstalled: 'bg-ink-100 text-ink-500',
  }
  return map[status] || ''
}

function reviewLabel(status) {
  const map = { pending: '待审', published: '已发布', hidden: '已隐藏' }
  return map[status] || status || ''
}

function priceLabel(listing) {
  if (!listing) return '—'
  const pricing = listing.pricing || {}
  const price = Number(pricing.price || 0)
  if (!price || listing.pricing_mode === 'free' || pricing.mode === 'free') {
    return pricing.trial_days ? `免费试用 ${pricing.trial_days} 天` : '免费'
  }
  const currency = pricing.currency || 'CNY'
  return `${currency} ${price.toFixed(2)}`
}

function installOf(listing) {
  if (!listing) return null
  return installsMap.value[listing.id] || null
}

async function loadListings() {
  if (!api) {
    error.value = '应用市场接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await api.list('listings/', {
      page: page.value,
      page_size: pageSize.value,
      q: debouncedQ.value.trim() || undefined,
      category_id: categoryId.value || undefined,
      pricing_mode: pricingMode.value || undefined,
      sort: sort.value,
    })
    items.value = data.items || []
    total.value = Number(data.count) || 0
    page.value = Number(data.page) || page.value
    if (!items.value.length && total.value > 0 && page.value > pages.value) {
      page.value = pages.value
      await loadListings()
    }
  } catch (e) {
    items.value = []
    total.value = 0
    error.value = e?.message || '应用目录加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
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

async function loadMyInstalls() {
  try {
    const data = await api.list('installs/', { page: 1, page_size: 100 })
    const map = {}
    for (const row of data.items || []) {
      if (row?.listing?.id) map[row.listing.id] = row
    }
    installsMap.value = map
  } catch (e) {
    installsMap.value = {}
  }
}

function goPage(next) {
  const target = Math.min(Math.max(1, Number(next) || 1), pages.value)
  if (target === page.value) return
  page.value = target
  loadListings()
}

function resetFilters() {
  q.value = ''
  debouncedQ.value = ''
  categoryId.value = ''
  pricingMode.value = ''
  sort.value = 'relevance'
  page.value = 1
  loadListings()
}

async function openDetail(item) {
  if (!item) return
  detailOpen.value = true
  detail.value = item
  detailError.value = ''
  reviews.value = []
  reviewTotal.value = 0
  reviewPage.value = 1
  reviewSummary.value = null
  reviewError.value = ''
  Object.keys(repliesMap).forEach((key) => delete repliesMap[key])
  await Promise.all([loadDetail(item.id), loadReviews(true)])
}

async function loadDetail(id) {
  if (!id) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await api.get(`listings/${id}/`)
  } catch (e) {
    detailError.value = e?.message || '应用详情加载失败'
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function loadReviews(reset = true) {
  const id = detail.value?.id
  if (!id) return
  if (reset) {
    reviewPage.value = 1
    reviews.value = []
  }
  reviewLoading.value = true
  reviewError.value = ''
  try {
    const data = await api.list(`listings/${id}/reviews/`, { page: reviewPage.value, page_size: 10 })
    reviews.value = reset ? data.items || [] : [...reviews.value, ...(data.items || [])]
    reviewTotal.value = Number(data.count) || 0
    reviewSummary.value = data.summary || null
    if ((data.items || []).length) reviewPage.value += 1
  } catch (e) {
    reviewError.value = e?.message || '评价加载失败'
    app.toastMsg(reviewError.value, 'error')
  } finally {
    reviewLoading.value = false
  }
}

async function toggleHelpful(row) {
  try {
    await api.post(`reviews/${row.id}/helpful/`)
    await loadReviews(true)
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  }
}

async function toggleReplies(row) {
  if (repliesMap[row.id]) {
    delete repliesMap[row.id]
    if (replyTargetId.value === row.id) replyTargetId.value = 0
    return
  }
  repliesLoading[row.id] = true
  try {
    const data = await api.list(`reviews/${row.id}/replies/`, { page: 1, page_size: 100 })
    repliesMap[row.id] = data.items || []
    replyTargetId.value = row.id
  } catch (e) {
    app.toastMsg(e?.message || '回复加载失败', 'error')
    repliesMap[row.id] = []
  } finally {
    repliesLoading[row.id] = false
  }
}

async function submitReply(row) {
  const content = String(replyDraft[row.id] || '').trim()
  if (!content) {
    app.toastMsg('请输入回复内容', 'info')
    return
  }
  replySaving.value = row.id
  try {
    await api.post(`reviews/${row.id}/replies/`, { content })
    replyDraft[row.id] = ''
    app.toastMsg('回复已提交', 'success')
    const data = await api.list(`reviews/${row.id}/replies/`, { page: 1, page_size: 100 })
    repliesMap[row.id] = data.items || []
  } catch (e) {
    app.toastMsg(e?.message || '回复失败', 'error')
  } finally {
    replySaving.value = 0
  }
}

async function submitReview() {
  const id = detail.value?.id
  if (!id) return
  reviewSubmitting.value = true
  try {
    await api.post(`listings/${id}/reviews/`, {
      rating: Number(reviewForm.rating) || 5,
      title: reviewForm.title.trim(),
      content: reviewForm.content.trim(),
    })
    reviewForm.title = ''
    reviewForm.content = ''
    reviewForm.rating = 5
    app.toastMsg('评价已提交，等待审核后展示', 'success')
    await Promise.all([loadReviews(true), loadDetail(id)])
  } catch (e) {
    app.toastMsg(e?.message || '评价提交失败', 'error')
  } finally {
    reviewSubmitting.value = false
  }
}

async function openInstall(item) {
  if (!item) return
  installTarget.value = item
  installOpen.value = true
  installVersionId.value = ''
  installVersions.value = []
  installVersionsError.value = ''
  installResolve.value = null
  installResolveError.value = ''
  installForm.auto_update = false
  installForm.config = ''
  await Promise.all([loadInstallVersions(item.id), resolveInstall(item.id)])
}

function closeInstall() {
  installOpen.value = false
  installTarget.value = null
  installSaving.value = false
}

async function loadInstallVersions(listingId) {
  installVersionsLoading.value = true
  try {
    const data = await api.list(`listings/${listingId}/versions/`, { page: 1, page_size: 50 })
    installVersions.value = (data.items || []).filter((row) => row.status === 'published')
  } catch (e) {
    installVersions.value = []
    installVersionsError.value = e?.message || '版本列表加载失败'
  } finally {
    installVersionsLoading.value = false
  }
}

async function resolveInstall(listingId) {
  installResolveLoading.value = true
  installResolveError.value = ''
  try {
    installResolve.value = await api.get(`installs/resolve/?listing_id=${listingId}`)
  } catch (e) {
    installResolve.value = null
    installResolveError.value = e?.message || '兼容性解析失败'
  } finally {
    installResolveLoading.value = false
  }
}

function parseConfig() {
  const raw = String(installForm.config || '').trim()
  if (!raw) return {}
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch (e) {
    throw new Error('初始化配置不是合法 JSON', { cause: e })
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('初始化配置必须是 JSON 对象')
  }
  return parsed
}

async function submitInstall() {
  if (!installTarget.value) return
  let config
  try {
    config = parseConfig()
  } catch (e) {
    app.toastMsg(e?.message || '配置格式错误', 'error')
    return
  }
  installSaving.value = true
  try {
    const payload = {
      listing_id: installTarget.value.id,
      auto_update: Boolean(installForm.auto_update),
      config,
    }
    if (installVersionId.value) payload.version_id = Number(installVersionId.value)
    const result = await api.post('installs/', payload)
    app.toastMsg(result?.action === 'already_installed' ? '应用已安装，配置已更新' : '安装成功', 'success')
    closeInstall()
    await loadMyInstalls()
    if (detail.value?.id === installTarget.value?.id) {
      // 安装态在抽屉底部按钮里同步，详情无需重新拉取
    }
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '安装失败', 'error')
  } finally {
    installSaving.value = false
  }
}

function askToggle(install, enable) {
  if (!install) return
  confirmTitle.value = enable ? '启用应用' : '停用应用'
  confirmText.value = enable
    ? '启用后应用将恢复可用，安装量保持不变。'
    : '停用后应用仍计入安装量，但当前用户无法继续使用。'
  confirmLabel.value = enable ? '确认启用' : '确认停用'
  confirmAction.value = async () => {
    await api.post(`installs/${install.id}/${enable ? 'enable' : 'disable'}/`)
    app.toastMsg(enable ? '已启用' : '已停用', 'success')
    await loadMyInstalls()
    emit('changed')
  }
  confirmOpen.value = true
}

function askUninstall(install) {
  if (!install) return
  confirmTitle.value = '卸载应用'
  confirmText.value = '卸载后安装记录保留以便重装，应用的本地配置将不再生效。'
  confirmLabel.value = '确认卸载'
  confirmAction.value = async () => {
    await api.post(`installs/${install.id}/uninstall/`)
    app.toastMsg('已卸载', 'success')
    await loadMyInstalls()
    if (detailOpen.value && detail.value?.id) await loadDetail(detail.value.id)
    emit('changed')
  }
  confirmOpen.value = true
}

async function runConfirm() {
  if (typeof confirmAction.value !== 'function') return
  confirmBusy.value = true
  try {
    await confirmAction.value()
    closeConfirm()
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    confirmBusy.value = false
  }
}

function closeConfirm() {
  confirmOpen.value = false
  confirmBusy.value = false
  confirmAction.value = null
}

function openReport(item) {
  if (!item) return
  reportTarget.value = item
  reportForm.reason = 'spam'
  reportForm.detail = ''
  reportOpen.value = true
}

function closeReport() {
  reportOpen.value = false
  reportTarget.value = null
  reportSaving.value = false
}

async function submitReport() {
  if (!reportTarget.value) return
  reportSaving.value = true
  try {
    await api.post('reports/', {
      listing_id: reportTarget.value.id,
      reason: reportForm.reason,
      detail: reportForm.detail.trim(),
    })
    app.toastMsg('举报已提交，平台会尽快核实', 'success')
    closeReport()
  } catch (e) {
    app.toastMsg(e?.message || '举报提交失败', 'error')
  } finally {
    reportSaving.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
  detail.value = null
  detailError.value = ''
  replyTargetId.value = 0
}

watch([debouncedQ, categoryId, pricingMode, sort], () => {
  page.value = 1
  loadListings()
})

watch(
  () => props.refreshKey,
  () => {
    loadListings()
    loadMyInstalls()
  }
)

onMounted(() => {
  loadCategories()
  loadMyInstalls()
  loadListings()
})
</script>