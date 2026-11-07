<template>
  <div class="min-w-0">
    <div
      v-if="!graph.nodes.length"
      class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400"
    >
      {{ emptyText }}
    </div>
    <div v-else class="overflow-x-auto overflow-y-hidden">
      <svg
        :viewBox="`0 0 ${graph.width} ${graph.height}`"
        :width="graph.width"
        :height="graph.height"
        class="max-w-none"
        role="img"
        :aria-label="ariaLabel"
      >
        <defs>
          <marker id="pg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
          <marker id="pg-arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#6366f1" />
          </marker>
        </defs>

        <g v-for="edge in graph.edges" :key="edge.id">
          <path
            :d="edge.path"
            fill="none"
            stroke="#cbd5e1"
            stroke-width="1.4"
            :marker-end="edge.active ? 'url(#pg-arrow-active)' : 'url(#pg-arrow)'"
          />
          <text
            v-if="edge.label"
            :x="edge.labelX"
            :y="edge.labelY"
            text-anchor="middle"
            class="fill-ink-400"
            font-size="9"
          >
            {{ edge.label }}
          </text>
        </g>

        <g
          v-for="node in graph.nodes"
          :key="node.key"
          class="cursor-pointer"
          tabindex="0"
          role="button"
          @click="emit('select', node.key)"
          @keydown.enter="emit('select', node.key)"
        >
          <rect
            :x="node.x"
            :y="node.y"
            :width="NODE_W"
            :height="NODE_H"
            rx="8"
            :fill="toneFor(node.type).fill"
            :stroke="selectedKey === node.key ? '#4f46e5' : toneFor(node.type).stroke"
            :stroke-width="selectedKey === node.key ? 2 : 1.2"
          />
          <text :x="node.x + 10" :y="node.y + 17" font-size="11" class="fill-ink-800" font-weight="600">
            {{ shorten(node.label) }}
          </text>
          <text :x="node.x + 10" :y="node.y + 32" font-size="9" class="fill-ink-500">
            {{ typeLabel(node.type) }}<tspan v-if="node.disabled"> · 已停用</tspan>
          </text>
        </g>
      </svg>
    </div>

    <div class="mt-2 flex flex-wrap items-center gap-1.5">
      <span class="text-[11px] text-ink-400">节点 {{ graph.nodes.length }} 个 · 连线 {{ graph.edges.length }} 条</span>
      <span v-if="graph.cyclic" class="tag bg-amber-50 text-amber-600">检测到环，已按序号兜底分层</span>
      <span v-else-if="graph.nodes.length" class="tag">分层 {{ graph.layerCount }} 级</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 节点：[{ key, label, type, enabled }] */
  nodes: { type: Array, default: () => [] },
  /** 连线：[{ source, target, label }] */
  edges: { type: Array, default: () => [] },
  selectedKey: { type: String, default: '' },
  emptyText: { type: String, default: '暂无节点，先添加 source 与 sink 节点' },
  ariaLabel: { type: String, default: '数据管道 DAG 拓扑图' },
})

const emit = defineEmits(['select'])

const NODE_W = 132
const NODE_H = 42
const GAP_X = 74
const GAP_Y = 24
const PAD = 18

const TYPE_LABELS = {
  source: '数据源',
  transform: '转换',
  filter: '过滤',
  aggregate: '聚合',
  join: '关联',
  sort: '排序',
  dedupe: '去重',
  map: '映射',
  sink: '输出',
  webhook: '回调',
}

const TYPE_TONES = {
  source: { fill: '#ecfdf5', stroke: '#6ee7b7' },
  transform: { fill: '#eff6ff', stroke: '#93c5fd' },
  filter: { fill: '#fffbeb', stroke: '#fcd34d' },
  aggregate: { fill: '#f5f3ff', stroke: '#c4b5fd' },
  join: { fill: '#eef2ff', stroke: '#a5b4fc' },
  sort: { fill: '#f0fdfa', stroke: '#5eead4' },
  dedupe: { fill: '#fff1f2', stroke: '#fda4af' },
  map: { fill: '#ecfeff', stroke: '#67e8f9' },
  sink: { fill: '#eef2ff', stroke: '#818cf8' },
  webhook: { fill: '#fff7ed', stroke: '#fdba74' },
}

function toneFor(type) {
  return TYPE_TONES[type] || { fill: '#f8fafc', stroke: '#cbd5e1' }
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type || '节点'
}

function shorten(text) {
  const value = String(text ?? '')
  return value.length > 15 ? `${value.slice(0, 15)}…` : value
}

function nodeKey(node, index) {
  return String(node.key ?? node.node_key ?? node.id ?? `node-${index}`)
}

const graph = computed(() => {
  const rawNodes = Array.isArray(props.nodes) ? props.nodes : []
  const seenKeys = new Set()
  const nodes = []
  rawNodes.forEach((node, index) => {
    const key = nodeKey(node, index)
    if (seenKeys.has(key)) return
    seenKeys.add(key)
    nodes.push({
      key,
      label: node.label ?? node.name ?? node.node_key ?? node.key ?? '未命名节点',
      type: node.type ?? node.node_type ?? '',
      disabled: node.disabled === true || node.enabled === false,
    })
  })

  const known = new Set(nodes.map((item) => item.key))
  const edges = (Array.isArray(props.edges) ? props.edges : [])
    .map((edge, index) => ({
      id: `e-${index}`,
      source: String(edge.source ?? edge.source_key ?? edge.from_key ?? edge.upstream_key ?? ''),
      target: String(edge.target ?? edge.target_key ?? edge.to_key ?? edge.downstream_key ?? ''),
      label: edge.label || edge.source_port || '',
      active: false,
    }))
    .filter((edge) => edge.source && edge.target && edge.source !== edge.target
      && known.has(edge.source) && known.has(edge.target))

  if (!nodes.length) {
    return { nodes: [], edges: [], width: 320, height: 120, layerCount: 0, cyclic: false }
  }

  // 入度 + Kahn 分层，环内节点兜底放到最后一层，保证图始终可渲染
  const indegree = new Map(nodes.map((item) => [item.key, 0]))
  for (const edge of edges) {
    indegree.set(edge.target, (indegree.get(edge.target) || 0) + 1)
  }
  const layer = new Map()
  const queue = nodes.filter((item) => !indegree.get(item.key)).map((item) => item.key)
  queue.forEach((key) => layer.set(key, 0))

  const remaining = new Map(indegree)
  let head = 0
  while (head < queue.length) {
    const key = queue[head]
    head += 1
    const currentLayer = layer.get(key) || 0
    for (const edge of edges) {
      if (edge.source !== key) continue
      layer.set(edge.target, Math.max(layer.get(edge.target) || 0, currentLayer + 1))
      remaining.set(edge.target, (remaining.get(edge.target) || 1) - 1)
      if (remaining.get(edge.target) === 0 && !queue.includes(edge.target)) {
        queue.push(edge.target)
      }
    }
  }

  let cyclic = false
  let maxLayer = 0
  layer.forEach((value) => { maxLayer = Math.max(maxLayer, value) })
  for (const item of nodes) {
    if (!layer.has(item.key)) {
      cyclic = true
      layer.set(item.key, maxLayer + 1)
    }
  }

  const byLayer = new Map()
  for (const item of nodes) {
    const value = layer.get(item.key) || 0
    if (!byLayer.has(value)) byLayer.set(value, [])
    byLayer.get(value).push(item)
  }
  const layerKeys = Array.from(byLayer.keys()).sort((a, b) => a - b)
  const tallest = Math.max(...layerKeys.map((key) => byLayer.get(key).length))
  const layerCount = layerKeys.length

  const positions = new Map()
  let cursor = 0
  for (const layerKey of layerKeys) {
    const column = byLayer.get(layerKey)
    const columnHeight = column.length * NODE_H + (column.length - 1) * GAP_Y
    const totalHeight = tallest * NODE_H + (tallest - 1) * GAP_Y
    const offset = (totalHeight - columnHeight) / 2
    column.forEach((item, index) => {
      positions.set(item.key, {
        x: PAD + cursor * (NODE_W + GAP_X),
        y: PAD + offset + index * (NODE_H + GAP_Y),
      })
    })
    cursor += 1
  }

  const width = PAD * 2 + layerCount * NODE_W + Math.max(0, layerCount - 1) * GAP_X
  const height = PAD * 2 + tallest * NODE_H + Math.max(0, tallest - 1) * GAP_Y

  const drawnEdges = edges.map((edge) => {
    const from = positions.get(edge.source)
    const to = positions.get(edge.target)
    if (!from || !to) return { ...edge, path: '', labelX: 0, labelY: 0 }
    const x1 = from.x + NODE_W
    const y1 = from.y + NODE_H / 2
    const x2 = to.x
    const y2 = to.y + NODE_H / 2
    const mid = (x1 + x2) / 2
    return {
      ...edge,
      path: `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`,
      labelX: mid,
      labelY: (y1 + y2) / 2 - 4,
    }
  })

  const drawnNodes = nodes.map((item) => {
    const position = positions.get(item.key) || { x: PAD, y: PAD }
    return { ...item, x: position.x, y: position.y }
  })

  return {
    nodes: drawnNodes,
    edges: drawnEdges,
    width,
    height,
    layerCount,
    cyclic,
  }
})
</script>