#ifndef NS3_SLICE_REGISTRY_H
#define NS3_SLICE_REGISTRY_H
#include <cstdint>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <utility>
#include <array>
namespace ns3 {
// SLICE PATCH: process-global slice state shared by the gNB MAC/scheduler, the scenario and (later) the E2 handler.
//   membership : IMSI -> slice (0 = eMBB, 1 = critical), (cellId, RNTI) -> IMSI
//   policy     : per-slice max symbol ratio, global or per cell (work-conserving, see scheduler)
class SliceRegistry {
public:
  static SliceRegistry& Instance();
  void SetUeSlice(uint64_t imsi, uint8_t slice){ std::lock_guard<std::mutex> l(m_mtx); m_imsiSlice[imsi]=slice; }
  void RegisterRnti(uint16_t cell, uint16_t rnti, uint64_t imsi){ std::lock_guard<std::mutex> l(m_mtx); m_rntiImsi[{cell,rnti}]=imsi; }
  void SetCurrentCell(uint16_t cell){ m_curCell=cell; }
  uint16_t CurrentCell() const { return m_curCell; }
  uint8_t SliceOf(uint16_t cell, uint16_t rnti){ std::lock_guard<std::mutex> l(m_mtx);
    auto a=m_rntiImsi.find({cell,rnti}); if(a==m_rntiImsi.end()){ m_miss++; m_lastMiss={cell,rnti}; return 0; }
    m_hit++; auto b=m_imsiSlice.find(a->second); return b==m_imsiSlice.end()?0:b->second; }
  void SetSliceMaxRatio(uint8_t slice,double r){ std::lock_guard<std::mutex> l(m_mtx); m_maxRatio[slice]=r; }
  void SetCellSliceMaxRatio(uint16_t cell,uint8_t slice,double r){ std::lock_guard<std::mutex> l(m_mtx); m_cellRatio[{cell,slice}]=r; }
  // B1 baseline (MCS capping, as in Hoffmann et al.): per-cell DL MCS cap, <0 removes it
  void SetCellMcsCap(uint16_t cell,int cap){ std::lock_guard<std::mutex> l(m_mtx); if(cap<0) m_mcsCap.erase(cell); else m_mcsCap[cell]=cap; }
  int McsCap(uint16_t cell){ std::lock_guard<std::mutex> l(m_mtx); auto a=m_mcsCap.find(cell); return a==m_mcsCap.end()?-1:a->second; }
  double SliceMaxRatio(uint16_t cell,uint8_t slice){ std::lock_guard<std::mutex> l(m_mtx);
    auto c=m_cellRatio.find({cell,slice}); if(c!=m_cellRatio.end()) return c->second;
    auto g=m_maxRatio.find(slice); return g==m_maxRatio.end()?1.0:g->second; }
  bool Enabled(){ std::lock_guard<std::mutex> l(m_mtx); return !m_maxRatio.empty() || !m_cellRatio.empty(); }
  std::string Stats(){ std::lock_guard<std::mutex> l(m_mtx); std::ostringstream o;
    o<<"lookups hit "<<m_hit<<" miss "<<m_miss<<" entries "<<m_rntiImsi.size()<<" lastMiss(cell,rnti)=("<<m_lastMiss.first<<","<<m_lastMiss.second<<") keys:"; int n=0; for(auto& kv:m_rntiImsi){ if(n++>=12) break; o<<" ("<<kv.first.first<<","<<kv.first.second<<")->"<<kv.second; } return o.str(); }
  // SLICE DEBUG: per-IMSI slice seen by the scheduler, symbols requested and symbols allocated
  void DebugDemand(uint16_t cell,uint16_t rnti,int sym){ std::lock_guard<std::mutex> l(m_mtx); uint64_t im=ImsiOfLocked(cell,rnti);
    auto& d=m_dbg[im]; auto b=m_imsiSlice.find(im); d[0]=(b==m_imsiSlice.end()?0:b->second); d[1]+=sym; }
  void DebugAlloc(uint16_t cell,uint16_t rnti,int sym){ std::lock_guard<std::mutex> l(m_mtx); m_dbg[ImsiOfLocked(cell,rnti)][2]+=sym; }
  void DebugTb(uint16_t cell,uint16_t rnti,uint32_t tb){ std::lock_guard<std::mutex> l(m_mtx); auto& d=m_dbg[ImsiOfLocked(cell,rnti)];
    if(tb<16) d[3]++; if(d[4]==0||tb<d[4]) d[4]=tb; }
  std::string DebugStr(){ std::lock_guard<std::mutex> l(m_mtx); std::ostringstream o;
    for(auto& kv:m_dbg) o<<" "<<kv.first<<":s"<<kv.second[0]<<":"<<kv.second[1]<<"/"<<kv.second[2]<<":tiny"<<kv.second[3]<<":minTB"<<kv.second[4]; return o.str(); }
private:
  SliceRegistry(){}
  uint64_t ImsiOfLocked(uint16_t cell,uint16_t rnti){ auto a=m_rntiImsi.find({cell,rnti}); return a==m_rntiImsi.end()?0:a->second; }
  std::map<uint64_t,std::array<uint64_t,5>> m_dbg;
  std::mutex m_mtx;
  std::map<uint64_t,uint8_t> m_imsiSlice;
  std::map<std::pair<uint16_t,uint16_t>,uint64_t> m_rntiImsi;
  std::map<uint8_t,double> m_maxRatio;
  std::map<std::pair<uint16_t,uint8_t>,double> m_cellRatio;
  std::map<uint16_t,int> m_mcsCap;
  uint16_t m_curCell=0;
  uint64_t m_hit=0, m_miss=0;
  std::pair<uint16_t,uint16_t> m_lastMiss{0,0};
};
}
#endif
