export const probesViewTemplate = `
<section class="panel">
  <h2>探头登记</h2>
  <p class="hint">探头须挂靠仓间；离线探头禁止新建批次。</p>
  <div class="form-row">
    <div><label>探头编码</label><input v-model="probeForm.probe_code"/></div>
    <div><label>仓间</label>
      <select v-model.number="probeForm.chamber_id">
        <option v-for="c in chambers" :key="c.id" :value="c.id">{{ c.chamber_code }} · {{ c.name }}</option>
      </select>
    </div>
    <div><label>型号</label><input v-model="probeForm.model"/></div>
    <div><label>校准到期</label><input v-model="probeForm.calibration_due" type="date"/></div>
  </div>
  <div class="actions">
    <button @click="registerProbe">登记探头</button>
    <button class="secondary" @click="refresh">刷新</button>
  </div>
  <h3>探头回写温度点</h3>
  <p class="hint">回写挂接批次采样点；已封批批次正式点列零改，回写将被拒并记温度点偏航（甲路径）。</p>
  <div class="form-row">
    <div><label>探头</label>
      <select v-model.number="writebackForm.probe_id">
        <option v-for="p in probes" :key="p.id" :value="p.id">{{ p.probe_code }}</option>
      </select>
    </div>
    <div><label>挂接批次</label>
      <select v-model.number="writebackForm.batch_id">
        <option v-for="b in writebackBatches" :key="b.id" :value="b.id">{{ b.batch_code }} · {{ b.status }}</option>
      </select>
    </div>
  </div>
  <label>回写温度点 JSON</label>
  <textarea v-model="writebackForm.points_json" rows="2" placeholder="[{&quot;t&quot;:&quot;16:00&quot;,&quot;c&quot;:-19}]"></textarea>
  <div class="actions"><button @click="doWriteback">回写温度点</button></div>
  <table class="data-table">
    <thead><tr><th>编码</th><th>仓间</th><th>区域</th><th>在线</th><th>到期</th><th></th></tr></thead>
    <tbody>
      <tr v-for="p in probes" :key="p.id" @click="selectProbe(p)">
        <td>{{ p.probe_code }}</td>
        <td>{{ p.chamber_code }}</td>
        <td>{{ p.region }}</td>
        <td><span class="badge" :class="probeOnlineClass(p.online_status)">{{ p.online_status }}</span></td>
        <td>{{ p.calibration_due }}</td>
        <td><button class="mini-btn" @click.stop="loadProbeDetail(p.id)">校准史</button></td>
      </tr>
    </tbody>
  </table>
  <div v-if="probeDetail" class="detail-box">
    <h3>探头 {{ probeDetail.probe.probe_code }}</h3>
    <p>目标温区 {{ probeDetail.probe.target_min }}~{{ probeDetail.probe.target_max }}℃</p>
    <ul><li v-for="c in probeDetail.calibrations" :key="c.id">{{ c.calibrated_at }} 偏移 {{ c.offset_c }}℃ 至 {{ c.valid_until }}</li></ul>
  </div>
</section>
`;
