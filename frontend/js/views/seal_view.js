export const sealViewTemplate = `
<section class="panel">
  <h2>封批升代</h2>
  <p class="hint">校准有效且无开放游标时方可封批；封批代生效后探头挂接温度点正式表零改（甲路径），偏离已封纪要记温度点偏航并拒写。</p>
  <div class="form-row">
    <div><label>批次</label>
      <select v-model.number="sealForm.batch_id"><option v-for="b in sealableBatches" :key="b.id" :value="b.id">{{ b.batch_code }}</option></select>
    </div>
    <div><label>快照附言</label><input v-model="sealForm.manifest"/></div>
  </div>
  <div class="actions"><button @click="doSeal">执行封批</button></div>
  <table class="data-table">
    <thead><tr><th>批次</th><th>代</th><th>封批时间</th><th>点数</th><th>点列校验</th><th>口径</th><th>附言摘要</th></tr></thead>
    <tbody>
      <tr v-for="s in seals" :key="s.id">
        <td>{{ s.batch_code }}</td>
        <td>{{ s.batch_generation }}</td>
        <td>{{ s.sealed_at }}</td>
        <td>{{ s.point_count }}</td>
        <td class="mono">{{ s.points_sha }}</td>
        <td>{{ s.policy_path ? s.policy_path + "路径·零改" : "—" }}</td>
        <td>{{ shortText(s.note || s.manifest) }}</td>
      </tr>
    </tbody>
  </table>
  <h3>封批温度点纪要（当班封死）</h3>
  <table class="data-table">
    <thead><tr><th>批次</th><th>代</th><th>口径</th><th>点数</th><th>班次</th><th>锁</th><th>裁决人</th><th>裁决</th></tr></thead>
    <tbody>
      <tr v-for="m in sealMemos" :key="m.id">
        <td>{{ m.batch_code }}</td>
        <td>{{ m.batch_generation }}</td>
        <td>{{ m.policy_path }}路径</td>
        <td>{{ m.point_count }}</td>
        <td>{{ m.shift_tag }}</td>
        <td><span class="badge pass">{{ m.locked ? "封死" : "开" }}</span></td>
        <td>{{ m.decided_by }}</td>
        <td>{{ shortText(m.decision) }}</td>
      </tr>
    </tbody>
  </table>
  <h3>温度点偏航记录</h3>
  <table class="data-table">
    <thead><tr><th>批次</th><th>时间</th><th>操作者</th><th>来源</th><th>原因</th></tr></thead>
    <tbody>
      <tr v-for="d in sealDeviations" :key="d.id">
        <td>{{ d.batch_code }}</td>
        <td>{{ d.created_at }}</td>
        <td>{{ d.actor }}</td>
        <td>{{ d.source }}</td>
        <td>{{ shortText(d.reason) }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;
