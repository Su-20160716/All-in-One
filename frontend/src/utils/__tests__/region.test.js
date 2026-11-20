import { describe, expect, it } from 'vitest'
import { cityDisplayName, composeAddress, regionPaths, searchRegions } from '../region'

describe('composeAddress', () => {
  it('拼接省市区与详细地址', () => {
    expect(composeAddress({
      province: '广东省',
      city: '深圳市',
      district: '南山区',
      detail: '科技园 1 号',
    })).toBe('广东省 深圳市 南山区 科技园 1 号')
  })

  it('跳过直辖市的“市辖区”占位节点', () => {
    expect(composeAddress({
      province: '北京市',
      city: '市辖区',
      district: '朝阳区',
      detail: '',
    })).toBe('北京市 朝阳区')
  })

  it('空值返回空串', () => {
    expect(composeAddress(null)).toBe('')
    expect(composeAddress({ province: '', city: '', district: '', detail: '  ' })).toBe('')
  })
})

describe('cityDisplayName', () => {
  it('“市辖区”不参与地址展示', () => {
    expect(cityDisplayName('市辖区')).toBe('')
    expect(cityDisplayName('深圳市')).toBe('深圳市')
  })
})

describe('地区搜索', () => {
  it('按区县关键字匹配全路径', () => {
    const hit = searchRegions('南山区', 50).find((item) => item.province === '广东省' && item.city === '深圳市')
    expect(hit).toBeTruthy()
    expect(hit.label).toBe('广东省 / 深圳市 / 南山区')
  })

  it('空关键字不返回结果', () => {
    expect(searchRegions('   ')).toEqual([])
  })

  it('索引包含三级区划', () => {
    expect(regionPaths.length).toBeGreaterThan(2000)
    expect(regionPaths.every((item) => item.province && item.city && item.district)).toBe(true)
  })
})
