<template>
  <Modal :show="show" :title="isEdit ? '编辑合同' : '新建合同'" width="640px" @close="$emit('close')">
    <form class="space-y-3" @submit.prevent="submit">
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">合同编号 <span class="text-rose-500">*</span></span>
          <input v-model.trim="form.number" class="input" maxlength="60" placeholder="例如 HT-2026-0001" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">合同名称 <span class="text-rose-500">*</span></span>
          <input v-model.trim="form.name" class="input" maxlength="200" placeholder="例如 年度运维服务合同" />
        </label>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">合同类型</span>
          <select v-model="form.contract_type" class="input">
            <option v-for="item in CONTRACT_TYPES" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">续约方式</span>
          <select v-model="form.renewal_mode" class="input">
            <option v-for="item in RENEWAL_MODES" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
      </div>

      <div class="grid gap-3 sm:grid-cols-3">
        <label class="block sm:col-span-2">
          <span class="mb-1 block text-[12px] text-ink-500">合同金额 <span class="text-rose-500">*</span></span>
          <input
            v-model="form.amount"
            class="input"
            type="number"
            min="0"
            step="0.01"
            placeholder="0.00"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">币种</span>
          <select v-model="form.currency" class="input">
            <option v-for="item in CURRENCIES" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">相对方</span>
          <input v-model.trim="form.counterparty_name" class="input" maxlength="200" placeholder="相对方主体名称" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">负责人</span>
          <input v-model.trim="form.responsible" class="input" maxlength="60" placeholder="负责人账号，可留空" />
        </label>
      </div>

      <div class="grid gap-3 sm:grid-cols-3">
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">签订日</span>
          <input v-model="form.sign_date" class="input" type="date" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">生效日</span>
          <input v-model="form.effective_date" class="input" type="date" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">到期日</span>
          <input v-model="form.expire_date" class="input" type="date" />
        </label>
      </div>

      <label class="block">
        <span class="mb-1 block text-[12px] text-ink-500">备注</span>
        <textarea v-model.trim="form.remark" class="input min-h-[64px]" maxlength="500" placeholder="补充说明，可留空" />
      </label>

      <p v-if="error" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ error }}</p>
      <p v-if="dateWarning" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-600">{{ dateWarning }}</p>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button class="btn-ghost" type="button" @click="$emit('close')">取消</button>
        <button class="btn-primary" type="submit" :disabled="submitting">
          {{ submitting ? '保存中…' : (isEdit ? '保存修改' : '创建合同') }}
        </button>
      </div>
    </form>
  </Modal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  contract: { type: Object, default: null },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'submit'])

const CONTRACT_TYPES = [
  { value: 'service', label: '服务合同' },
  { value: 'sales', label: '销售合同' },
  { value: 'purchase', label: '采购合同' },
  { value: 'lease', label: '租赁合同' },
  { value: 'labor', label: '劳务合同' },
  { value: 'license', label: '授权许可' },
  { value: 'nda', label: '保密协议' },
  { value: 'other', label: '其他类型' },
]

const RENEWAL_MODES = [
  { value: 'none', label: '不续约' },
  { value: 'auto', label: '自动续约' },
  { value: 'manual', label: '手动续约' },
  { value: 'negotiate', label: '协商续约' },
]

const CURRENCIES = ['CNY', 'USD', 'EUR', 'HKD', 'JPY', 'GBP']

function emptyForm() {
  return {
    number: '',
    name: '',
    contract_type: 'service',
    amount: '',
    currency: 'CNY',
    counterparty_name: '',
    responsible: '',
    sign_date: '',
    effective_date: '',
    expire_date: '',
    renewal_mode: 'none',
    remark: '',
  }
}

const form = ref(emptyForm())
const error = ref('')

const isEdit = computed(() => Boolean(props.contract?.id))

const dateWarning = computed(() => {
  if (!form.value.effective_date || !form.value.expire_date) return ''
  if (form.value.expire_date < form.value.effective_date) return '到期日早于生效日，请确认日期是否填反'
  return ''
})

function pickDate(value) {
  return String(value || '').slice(0, 10)
}

watch(
  () => props.show,
  (open) => {
    if (!open) return
    error.value = ''
    const source = props.contract
    if (source?.id) {
      form.value = {
        number: source.number || '',
        name: source.name || '',
        contract_type: source.contract_type || 'service',
        amount: source.amount ?? '',
        currency: source.currency || 'CNY',
        counterparty_name: source.counterparty_name || '',
        responsible: source.responsible_name || source.responsible || '',
        sign_date: pickDate(source.sign_date),
        effective_date: pickDate(source.effective_date),
        expire_date: pickDate(source.expire_date),
        renewal_mode: source.renewal_mode || 'none',
        remark: source.remark || '',
      }
      return
    }
    form.value = emptyForm()
  }
)

function validate() {
  if (!form.value.number) return '请填写合同编号'
  if (!form.value.name) return '请填写合同名称'
  const amount = Number(form.value.amount)
  if (!Number.isFinite(amount) || amount < 0) return '合同金额需要是不小于 0 的数字'
  if (form.value.effective_date && form.value.expire_date && form.value.expire_date < form.value.effective_date) {
    return '到期日不能早于生效日'
  }
  return ''
}

function submit() {
  const message = validate()
  if (message) {
    error.value = message
    return
  }
  error.value = ''
  const payload = {
    number: form.value.number,
    name: form.value.name,
    contract_type: form.value.contract_type,
    amount: Number(form.value.amount),
    currency: form.value.currency,
    counterparty_name: form.value.counterparty_name,
    sign_date: form.value.sign_date || null,
    effective_date: form.value.effective_date || null,
    expire_date: form.value.expire_date || null,
    renewal_mode: form.value.renewal_mode,
    remark: form.value.remark,
  }
  // 负责人既可能是用户主键也可能是账号名，按输入形态分别透传
  if (form.value.responsible) {
    if (/^\d+$/.test(form.value.responsible)) payload.responsible = Number(form.value.responsible)
    else payload.responsible_name = form.value.responsible
  }
  emit('submit', payload)
}
</script>