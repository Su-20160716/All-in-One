<template>
  <div ref="root" class="relative">
    <label class="mb-1 block text-[12px] font-medium text-ink-600">地址</label>
    <div class="relative">
      <input
        v-model="keyword"
        class="input pr-8"
        autocomplete="off"
        aria-label="搜索省市区"
        @focus="showSuggestions = true"
        @input="showSuggestions = true"
      />
      <svg class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="9" cy="9" r="5.5" stroke="currentColor" stroke-width="1.5" />
        <path d="m13.5 13.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
      </svg>
      <div v-if="showSuggestions && keyword.trim()" class="absolute z-40 mt-1 w-full overflow-hidden rounded-control border border-ink-100 bg-white shadow-pop">
        <button
          v-for="s in suggestions"
          :key="s.label"
          type="button"
          class="block w-full px-3 py-2 text-left text-[12px] text-ink-700 hover:bg-brand-50"
          @click="choose(s)"
        >{{ s.label }}</button>
        <div v-if="!suggestions.length" class="px-3 py-2 text-[12px] text-ink-400">没有匹配的省 / 市 / 区</div>
      </div>
    </div>
    <p class="mt-1 text-[11px] text-ink-400">输入省 / 市 / 区关键字可自动补全，也可在下方逐级选择</p>

    <div class="mt-2 grid grid-cols-3 gap-2">
      <select v-model="provinceCode" class="input px-2" aria-label="省份" @change="onProvinceChange">
        <option value="">省份</option>
        <option v-for="p in provinceList" :key="p.code" :value="p.code">{{ p.name }}</option>
      </select>
      <select
        v-model="cityCode"
        class="input px-2"
        aria-label="城市"
        :disabled="!provinceCode"
        @change="onCityChange"
      >
        <option value="">城市</option>
        <option v-for="c in cityList" :key="c.code" :value="c.code">{{ cityDisplayName(c.name) || province?.name || c.name }}</option>
      </select>
      <select v-model="districtCode" class="input px-2" aria-label="区县" :disabled="!cityCode">
        <option value="">区县</option>
        <option v-for="a in districtList" :key="a.code" :value="a.code">{{ a.name }}</option>
      </select>
    </div>

    <div class="mt-2">
      <label for="register-address-detail" class="mb-1 block text-[11px] text-ink-400">详细地址（选填）</label>
      <input
        id="register-address-detail"
        v-model="detail"
        class="input"
        maxlength="120"
        autocomplete="street-address"
      />
    </div>
    <p v-if="preview" class="mt-1.5 text-[11px] text-ink-500">已选：{{ preview }}</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { cityDisplayName, composeAddress, provinces, searchRegions } from '../utils/region'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({ province: '', city: '', district: '', detail: '' }),
  },
})
const emit = defineEmits(['update:modelValue'])

const root = ref(null)
const keyword = ref('')
const showSuggestions = ref(false)
const provinceCode = ref('')
const cityCode = ref('')
const districtCode = ref('')
const detail = ref('')

const provinceList = provinces
const province = computed(() => provinceList.find((p) => p.code === provinceCode.value) || null)
const cityList = computed(() => province.value?.children || [])
const city = computed(() => cityList.value.find((c) => c.code === cityCode.value) || null)
const districtList = computed(() => city.value?.children || [])
const district = computed(() => districtList.value.find((a) => a.code === districtCode.value) || null)

const suggestions = computed(() => searchRegions(keyword.value))
const preview = computed(() => composeAddress({
  province: province.value?.name || '',
  city: city.value?.name || '',
  district: district.value?.name || '',
  detail: detail.value,
}))

// 用传入的初始值回填三级选择（例如表单回显）
function initFromValue() {
  const value = props.modelValue || {}
  const p = provinceList.find((x) => x.name === value.province)
  provinceCode.value = p?.code || ''
  const c = p?.children?.find((x) => x.name === value.city)
  cityCode.value = c?.code || ''
  const a = c?.children?.find((x) => x.name === value.district)
  districtCode.value = a?.code || ''
  detail.value = value.detail || ''
}
initFromValue()

function onProvinceChange() {
  cityCode.value = ''
  districtCode.value = ''
}

function onCityChange() {
  districtCode.value = ''
}

function choose(item) {
  provinceCode.value = provinceList.find((p) => p.name === item.province)?.code || ''
  cityCode.value = province.value?.children.find((c) => c.name === item.city)?.code || ''
  districtCode.value = city.value?.children.find((a) => a.name === item.district)?.code || ''
  keyword.value = ''
  showSuggestions.value = false
}

watch([provinceCode, cityCode, districtCode, detail], () => {
  emit('update:modelValue', {
    province: province.value?.name || '',
    city: city.value?.name || '',
    district: district.value?.name || '',
    detail: detail.value.trim(),
  })
})

function onDocClick(e) {
  if (showSuggestions.value && root.value && !root.value.contains(e.target)) {
    showSuggestions.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>
