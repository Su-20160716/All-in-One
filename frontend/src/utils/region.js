/**
 * 省 / 市 / 区数据与地址工具
 * 数据源：china-division（MIT）pca-code.json，包含 31 个省级行政区的三级区划。
 */
import pca from 'china-division/dist/pca-code.json'

// 直辖市 / 省直辖县级区划的“市级”节点只是占位，拼接地址时跳过
const CITY_PLACEHOLDERS = new Set(['市辖区', '县'])

export const provinces = pca

export function cityDisplayName(name) {
  return CITY_PLACEHOLDERS.has(name) ? '' : name
}

/** 把级联选择结果拼成一行地址：广东省 深圳市 南山区 科技园 1 号 */
export function composeAddress(sel) {
  if (!sel) return ''
  return [sel.province, cityDisplayName(sel.city), sel.district, (sel.detail || '').trim()]
    .filter(Boolean)
    .join(' ')
}

/** 自动补全索引：每个区县一条“省 / 市 / 区”全路径 */
export const regionPaths = pca.flatMap((province) =>
  (province.children || []).flatMap((city) =>
    (city.children || []).map((area) => ({
      province: province.name,
      city: city.name,
      district: area.name,
      label: [province.name, cityDisplayName(city.name), area.name].filter(Boolean).join(' / '),
    }))
  )
)

/** 按关键字模糊搜索省市区全路径（最多返回 limit 条） */
export function searchRegions(keyword, limit = 8) {
  const q = (keyword || '').trim().toLowerCase()
  if (!q) return []
  const hits = []
  for (const item of regionPaths) {
    if (item.label.toLowerCase().includes(q)) {
      hits.push(item)
      if (hits.length >= limit) break
    }
  }
  return hits
}
