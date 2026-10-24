/**
 * 纯 JS SHA-1（增量计算）—— F14 秒传前置：上传前算真实 sha1
 *
 * 为什么不直接用 crypto.subtle.digest('SHA-1')：
 *   1) 它不支持增量，大文件必须一次性读进内存；
 *   2) 只在安全上下文（https 或 localhost）可用，http 内网/IP 访问直接抛异常。
 * 自己实现：分片喂数据、任何环境可用；调用方在失败时降级为不传 sha1
 * （后端 uploadInit 对空 sha1 按无秒传处理，只是少一个优化，不影响功能）。
 *
 * 与后端 hashlib.sha1().hexdigest() 输出完全一致（小写 40 位十六进制）。
 */

function rotl(n, s) {
  return (n << s) | (n >>> (32 - s))
}

export class Sha1 {
  constructor() {
    this.h0 = 0x67452301
    this.h1 = 0xEFCDAB89
    this.h2 = 0x98BADCFE
    this.h3 = 0x10325476
    this.h4 = 0xC3D2E1F0
    this.buf = new Uint8Array(64)
    this.bufLen = 0
    this.totalLen = 0
    this.finished = false
  }

  _processBlock(block) {
    const w = new Uint32Array(80)
    for (let i = 0; i < 16; i++) {
      w[i] = (block[i * 4] << 24) | (block[i * 4 + 1] << 16) | (block[i * 4 + 2] << 8) | block[i * 4 + 3]
    }
    for (let i = 16; i < 80; i++) {
      w[i] = rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1)
    }
    let a = this.h0, b = this.h1, c = this.h2, d = this.h3, e = this.h4
    for (let i = 0; i < 80; i++) {
      let f, k
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5A827999 } else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1 } else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC } else { f = b ^ c ^ d; k = 0xCA62C1D6 }
      const t = (rotl(a, 5) + f + e + k + w[i]) | 0
      e = d; d = c; c = rotl(b, 30); b = a; a = t
    }
    this.h0 = (this.h0 + a) | 0
    this.h1 = (this.h1 + b) | 0
    this.h2 = (this.h2 + c) | 0
    this.h3 = (this.h3 + d) | 0
    this.h4 = (this.h4 + e) | 0
  }

  /** 喂入一段字节（Uint8Array / ArrayBuffer） */
  update(data) {
    if (this.finished) throw new Error('Sha1 已 finalize，不能继续 update')
    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data)
    this.totalLen += bytes.length
    let offset = 0
    // 先补满上一次的残余块
    if (this.bufLen > 0) {
      const need = Math.min(64 - this.bufLen, bytes.length)
      this.buf.set(bytes.subarray(0, need), this.bufLen)
      this.bufLen += need
      offset = need
      if (this.bufLen === 64) {
        this._processBlock(this.buf)
        this.bufLen = 0
      }
    }
    // 整块直接处理，零拷贝
    while (offset + 64 <= bytes.length) {
      this._processBlock(bytes.subarray(offset, offset + 64))
      offset += 64
    }
    // 尾块入缓冲
    if (offset < bytes.length) {
      this.buf.set(bytes.subarray(offset), 0)
      this.bufLen = bytes.length - offset
    }
    return this
  }

  /** 结束计算，返回小写 40 位十六进制 */
  hex() {
    if (!this.finished) {
      const bitLen = this.totalLen * 8
      // 补 0x80 + 零填充到 56 mod 64，再追加 64 位大端长度
      this.update(new Uint8Array([0x80]))
      const zeros = new Uint8Array((this.bufLen <= 56 ? 56 : 120) - this.bufLen)
      this.totalLen -= zeros.length // update 会把 padding 也算进长度，这里手动抵掉
      this.update(zeros)
      const lenBytes = new Uint8Array(8)
      const view = new DataView(lenBytes.buffer)
      view.setUint32(0, Math.floor(bitLen / 0x100000000))
      view.setUint32(4, bitLen >>> 0)
      this.update(lenBytes)
      this.finished = true
    }
    const hv = [this.h0, this.h1, this.h2, this.h3, this.h4]
    return hv.map((h) => (h >>> 0).toString(16).padStart(8, '0')).join('')
  }
}

const SLICE_SIZE = 4 * 1024 * 1024 // 4MB 一片，与上传分片量级一致，内存友好

/**
 * 计算 File/Blob 的 sha1（分片读取，片间让出事件循环防卡 UI）。
 * @param {Blob} file
 * @param {(loaded: number, total: number) => void} [onProgress]
 * @returns {Promise<string>} 小写 40 位十六进制
 */
export async function sha1File(file, onProgress) {
  const sha = new Sha1()
  const total = file.size
  let loaded = 0
  for (let start = 0; start < total; start += SLICE_SIZE) {
    const slice = file.slice(start, Math.min(start + SLICE_SIZE, total))
    const buf = await slice.arrayBuffer()
    sha.update(new Uint8Array(buf))
    loaded += buf.byteLength
    onProgress?.(loaded, total)
    // 让出主线程，保持上传队列 UI 响应
    await new Promise((r) => setTimeout(r, 0))
  }
  return sha.hex()
}

export default sha1File
