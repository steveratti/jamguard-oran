/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */
// RIC-TaaP xApps
// Zero-Touch ES with cell utilization xApp

#include "../../../../src/xApp/e42_xapp_api.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_struct.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_list.h"
#include "../../../../src/util/time_now_us.h"
#include "../../../../src/util/alg_ds/ds/lock_guard/lock_guard.h"
#include "../../../../src/sm/rc_sm/rc_sm_id.h"
#include "../../../../src/sm/rc_sm/ie/rc_data_ie.h"
#include "../../../../src/util/e.h"

#include <unistd.h>

#define MIN_SINR -10

typedef struct {
    const e2_node_arr_xapp_t* nodes;
    struct SINRNeighboringValues* neighCells;
    int ueID;
    uint8_t frmCurntCell;
    uint8_t toTargetCell;
} callback_data_t;

typedef uint16_t (*Callback)(callback_data_t);

typedef enum {
    CONNECTED_MODE_MOBILITY = 3,
    ENERGY_STATE = 300
} rc_ctrl_service_style_id_e;
  
typedef enum {
    CELL_OFF = '0',
    CELL_ON = '1',  
    CELL_SLEEP = '2',
} cell_state_e;
  
typedef enum {
    QOS_FLOW_ID_1 = 1,
    QOS_FLOW_ID_10 = 10
} qos_flow_id_e;

typedef enum {
    DRB_ID_3 = 3
} drb_id_e;
  
typedef enum {
    PDU_SESSION_ID_5 = 5
} pdu_session_id_e;
  
static size_t ho_node_idx = 0;
static ue_id_e2sm_t ue_id;

static uint64_t const period_ms = 100;

static pthread_mutex_t mtx;

/*
each cell has connected UEs(with SINR value),
each Cell have neighbours of cells(with SINR value)
All of them in one indication message per Cell
*/

// ctrl after this
const int MAX_NUM_OF_RIC_INDICATIONS = 5;
struct SINRNeighboringValues 
{
  bool is_available;
  uint16_t neighCellID;
  double sinr;
  int counter;
};

struct SINRServingValues 
{
  bool is_available;
  uint16_t ueID;
  double sinr;
  struct SINRNeighboringValues* neighCells;  // array
  size_t numOfNeighCells;
  bool handover_in_progress;
};

// Per Cell
struct SINR_Map 
{
  uint16_t cellID;
  struct SINRServingValues* connectedUEs;  // array
  size_t numOfConnectedUEs;
  bool is_running;
  bool pending_shutdown;  // Track if cell is marked for shutdown
  time_t shutdown_start_time; // Track when shutdown process started
};

struct registeredCells {
  bool is_registered;
  struct SINR_Map* sinrMap;
};

#define MAX_REGISTERED_CELLS 10
#define MAX_REGISTERED_UES 20
#define MAX_REGISTERED_NEIGHBOURS 20

struct registeredCells cells_sinr_map[MAX_REGISTERED_CELLS] = {{false, NULL}};

/*

struct SINR_MapCells
{
  struct SINR_Map* sinrMapForCells;
  size_t numOfsinrMapForCells;
};

L3servingSINR3gpp_cell_5_UEID_00002, sinr= 2.0000 [db]
L3neighSINRListOf_UEID_00002, Neighbour=4
L3neighSINRListOf_UEID_00002, sinr= -12.0000 [db]
L3neighSINRListOf_UEID_00002, Neighbour=2
L3neighSINRListOf_UEID_00002, sinr= -13.0000 [db]
L3neighSINRListOf_UEID_00002, Neighbour=3
L3neighSINRListOf_UEID_00002, sinr= -16.0000 [db]

Based on SINR
struct targetCell{
UEid(IMSI), cellID
}

// int x -->> int* y = &x;  --> int** z = &y
// int* a = &z

*/

static
struct SINR_Map* add_SINR(const uint16_t cellID) 
{
  assert(cellID != 0);
  if (cells_sinr_map[cellID].sinrMap == NULL && !cells_sinr_map[cellID].is_registered) {
    cells_sinr_map[cellID].sinrMap = (struct SINR_Map*)calloc(1, sizeof(struct SINR_Map));
    cells_sinr_map[cellID].is_registered = true;
    cells_sinr_map[cellID].sinrMap->cellID = cellID;
    cells_sinr_map[cellID].sinrMap->connectedUEs = NULL;
    cells_sinr_map[cellID].sinrMap->numOfConnectedUEs = 0;
    cells_sinr_map[cellID].sinrMap->pending_shutdown = false;
    cells_sinr_map[cellID].sinrMap->shutdown_start_time = 0;
  }
  return cells_sinr_map[cellID].sinrMap;
}

// Serving msg
static
void add_UE(struct SINR_Map* cell, const uint16_t ueID, const double sinr) 
{
  assert(cell != NULL);
  if (cell->connectedUEs == NULL /*&& cell->numOfConnectedUEs == 0*/) {
    cell->connectedUEs = (struct SINRServingValues*)calloc(MAX_REGISTERED_UES, sizeof(struct SINRServingValues));

    // struct SINRServingValues* UE = &cell->connectedUEs[ueID];//cell->numOfConnectedUEs];
    cell->connectedUEs[ueID].ueID = ueID;
    cell->connectedUEs[ueID].sinr = sinr;
    cell->connectedUEs[ueID].neighCells = NULL;
    cell->connectedUEs[ueID].numOfNeighCells = 0;
    cell->connectedUEs[ueID].handover_in_progress = false;
  } else 
  {
    assert(cell->connectedUEs != NULL);
    assert(cell->numOfConnectedUEs != 0);
    assert(ueID <= MAX_REGISTERED_UES);

    // cell->connectedUEs = (struct SINRServingValues*) realloc(cell->connectedUEs, (cell->numOfConnectedUEs + 1) * sizeof(struct SINRServingValues));
    // struct SINRServingValues* UE = &cell->connectedUEs[cell->numOfConnectedUEs+1];
    // struct SINRServingValues* UE = &cell->connectedUEs[ueID];
    cell->connectedUEs[ueID].ueID = ueID;
    cell->connectedUEs[  ueID].sinr = sinr;
  }
  cell->connectedUEs[ueID].is_available = true;
  cell->numOfConnectedUEs += 1;
}

static
struct SINRServingValues* get_UE(const uint16_t cellID, const uint16_t ueID) 
{
  if (cells_sinr_map[cellID].is_registered) {
    assert(cells_sinr_map[cellID].sinrMap->connectedUEs[ueID].ueID == ueID);

    return &(cells_sinr_map[cellID].sinrMap->connectedUEs[ueID]);
    // printf("x->ueID=%d, ueID=%d\n", x->ueID , ueID);
    // return x;
    // for (size_t i = 0; i < cells_sinr_map[cellID].sinrMap->numOfConnectedUEs; i++)
    // {
    //   if(cells_sinr_map[cellID].sinrMap->connectedUEs[i].ueID == ueID) {
    //     return &cells_sinr_map[cellID].sinrMap->connectedUEs[i];
    //   }
    // }
  }
  return NULL;
}

/*
DoRecvLteMmWaveHandoverCompleted
*/

// m_rrc
// m_lastMmWaveCell[[a-z]+\] =
// m_lastMmWaveCell[m_[a-z]+\] =
// m_lastMmWaveCell[m
// DoRecvLteMmWaveHandoverCompleted
// UeManager::RecvRrcConnectionReconfigurationCompleted(MC_CONNECTION_RECONFIGURATION OR CONNECTION_RECONFIGURATION)

// LteEnbRrc::DoRecvRrcConnectionReconfigurationCompleted
// LteEnbRrc::DoRecvLteMmWaveHandoverCompleted --> IMP (m_lastMmWaveCell[imsi] = params.targetCellId;)

#define MAX_NUM_OF_RIC_INDICATIONS 5

static
void add_neighCell(struct SINRServingValues* UE, const uint16_t neighCellID, const double sinr) 
{
  assert(UE != NULL);

  // Initialize neighbor cells array if needed
  if (UE->neighCells == NULL) {
    UE->neighCells = (struct SINRNeighboringValues*)calloc(MAX_REGISTERED_NEIGHBOURS,
                                                           sizeof(struct SINRNeighboringValues));
    assert(UE->neighCells != NULL);
  }

  // Get reference to this neighbor cell
  struct SINRNeighboringValues* neighCell = &UE->neighCells[neighCellID];

  // Initialize new neighbor cell
  if (!neighCell->is_available) {
    neighCell->neighCellID = neighCellID;
    neighCell->sinr = sinr;
    neighCell->counter = 1;
    neighCell->is_available = true;
    UE->numOfNeighCells++;

    printf("New neighbor cell %d added for UE %d with initial SINR %.2f\n", neighCellID, UE->ueID, sinr);
  }
  // Update existing neighbor cell
  else {
    // Track measurements until we have MAX_NUM_OF_RIC_INDICATIONS samples
    if (neighCell->counter < MAX_NUM_OF_RIC_INDICATIONS) {
      // Update running sum
      neighCell->sinr = ((neighCell->sinr * neighCell->counter) + sinr) / (neighCell->counter + 1);
      neighCell->counter++;

      printf("Updated neighbor cell %d for UE %d: SINR %.2f (sample %d/%d)\n", neighCellID, UE->ueID,
             neighCell->sinr, neighCell->counter, MAX_NUM_OF_RIC_INDICATIONS);
    }
    // Reset after MAX_NUM_OF_RIC_INDICATIONS samples
    else 
    {
      neighCell->sinr = sinr;
      neighCell->counter = 1;

      printf("Reset neighbor cell %d for UE %d with new SINR %.2f\n", neighCellID, UE->ueID, sinr);
    }
  }
}

static
uint16_t getTargetCellID(callback_data_t data)
{
  assert(data.neighCells != NULL);

  double max_sinr = MIN_SINR;
  uint16_t targetCell = 0;

  printf("\n=== Target Cell Selection for UE %d ===\n", data.ueID);
  printf("Current Cell: %d\n", data.frmCurntCell);

  // Find cell with best SINR among neighbors
  for (int i = 0; i < MAX_REGISTERED_NEIGHBOURS; i++)
  {
    if (data.neighCells[i].is_available && 
        data.neighCells[i].counter >= MAX_NUM_OF_RIC_INDICATIONS) {
      
      // Skip cells marked for shutdown
      if (cells_sinr_map[i].sinrMap != NULL && 
          cells_sinr_map[i].sinrMap->pending_shutdown) {
        printf("Skipping Cell %d: marked for shutdown\n", i);
        continue;
      }

      printf("Evaluating Cell %d: SINR %.2f dB\n", i, data.neighCells[i].sinr);

      if (data.neighCells[i].sinr > MIN_SINR && 
          data.neighCells[i].sinr > max_sinr) {
        max_sinr = data.neighCells[i].sinr;
        targetCell = i;
        printf("Found better cell: %d (SINR: %.2f dB)\n", targetCell, max_sinr);
      }
    }
  }

  if (targetCell != 0) {
    printf("Selected Target Cell: %d (SINR: %.2f dB)\n", targetCell, max_sinr);
  } else 
  {
    printf("No suitable target cell found (SINR > %d dB required)\n", MIN_SINR);
  }

  return targetCell;
}

// TODO
void remove_UE() {}
void remove_neighCell() {}

// T Search(fp);
// GetIMSI, getSINR, findX, getTargetCell(sinrMap, targetCell)
// seach(findXX);

struct InfoObj 
{
  uint16_t cellID;
  uint16_t ueID;
};

// struct InfoObj parseStr()
static
struct InfoObj parseServingMsg(const char* msg) 
{
  struct InfoObj info;

  int ret = sscanf(msg, "L3servingSINR3gpp_cell_%hd_UEID_%hd", &info.cellID, &info.ueID);

  if (ret == 2)
    return info;

  info.cellID = -1;
  info.ueID = -1;
  return info;
}

static
struct InfoObj parseNeighMsg(const char* msg) 
{
  struct InfoObj info;

  int ret = sscanf(msg, "L3neighSINRListOf_UEID_%hd_of_Cell_%hd", &info.ueID, &info.cellID);

  if (ret == 2)
    return info;

  info.ueID = -1;
  info.cellID = -1;
  return info;
}

static
bool isMeasNameContains(const char* meas_name, const char* name) 
{
  return strncmp(meas_name, name, strlen(name)) == 0;
}

static
void log_kpm_measurements(kpm_ind_msg_format_1_t const* msg_frm_1)
{
  assert(msg_frm_1->meas_info_lst_len > 0 && "Cannot correctly print measurements");

  // assert(msg_frm_1->meas_info_lst_len == msg_frm_1->meas_data_lst_len && "meas_info_lst_len not equal
  // meas_data_lst_len");
  if (msg_frm_1->meas_info_lst_len != msg_frm_1->meas_data_lst_len) {
    printf("Error: meas_info_lst_len= (%ld) not equal meas_data_lst_len= (%ld)\n", msg_frm_1->meas_info_lst_len,
           msg_frm_1->meas_data_lst_len);
    return;
  }

  // UE Measurements per granularity period
  for (size_t i = 0; i < msg_frm_1->meas_info_lst_len; i++) 
  {
    meas_type_t const meas_type = msg_frm_1->meas_info_lst[i].meas_type;
    meas_data_lst_t const data_item = msg_frm_1->meas_data_lst[i];

    for (size_t j = 0; j < data_item.meas_record_len;) {
      meas_record_lst_t const record_item = data_item.meas_record_lst[j];

      if (meas_type.type == NAME_MEAS_TYPE) {
        char *meas_name_str = cp_ba_to_str(meas_type.name);
        if (isMeasNameContains(meas_name_str, "L3servingSINR3gpp_cell_")) {
          struct InfoObj info = parseServingMsg(meas_name_str);
          double sinr = record_item.real_val;

          struct SINR_Map* cell = add_SINR(info.cellID);
          add_UE(cell, info.ueID, sinr);

          printf("Serving Cell %d - UE %d: %.2f dB\n", info.cellID, info.ueID, sinr);

        } else if (isMeasNameContains(meas_name_str, "L3neighSINRListOf_UEID_")) {
          struct InfoObj info = parseNeighMsg(meas_name_str);

          meas_record_lst_t const sinr = record_item;
          meas_record_lst_t const NeighbourID = data_item.meas_record_lst[j + 1];

          struct SINRServingValues* UE = get_UE(info.cellID, info.ueID);
          assert(UE != NULL);

          add_neighCell(UE, NeighbourID.int_val, sinr.real_val);
          j += 2;
          continue;
        }
        free(meas_name_str);
      }
      j++;
    }
  }
}

static
void sm_cb_kpm(sm_ag_if_rd_t const* rd)
{
  assert(rd != NULL);
  assert(rd->type == INDICATION_MSG_AGENT_IF_ANS_V0);
  assert(rd->ind.type == KPM_STATS_V3_0);

  // Reading Indication Message Format 3
  kpm_ind_data_t const* ind = &rd->ind.kpm.ind;
  kpm_ind_msg_format_3_t const* msg_frm_3 = &ind->msg.frm_3;

  // uint64_t const now = time_now_us();
  static int counter = 1;
  {
    lock_guard(&mtx);

    // Reported list of measurements per UE
    for (size_t i = 0; i < msg_frm_3->ue_meas_report_lst_len; i++) 
    {
      // Save UE ID for filling RC Control message
      free_ue_id_e2sm(&ue_id);
      ue_id = cp_ue_id_e2sm(&msg_frm_3->meas_report_per_ue[i].ue_meas_report_lst);

      // log measurements
      log_kpm_measurements(&msg_frm_3->meas_report_per_ue[i].ind_msg_format_1);
    }
    counter++;
  }
}

static
test_info_lst_t filter_predicate(test_cond_type_e type, test_cond_e cond, int value)
{
  test_info_lst_t dst = {0};

  dst.test_cond_type = type;
  dst.IsStat = TRUE_TEST_COND_TYPE;

  // Allocate memory for test_cond and set its value
  dst.test_cond = calloc(1, sizeof(test_cond_e));
  assert(dst.test_cond != NULL && "Memory allocation failed for test_cond");
  *dst.test_cond = cond;

  // Allocate memory for test_cond_value
  dst.test_cond_value = calloc(1, sizeof(test_cond_value_t));
  assert(dst.test_cond_value != NULL && "Memory allocation failed for test_cond_value");
  dst.test_cond_value->type = INTEGER_TEST_COND_VALUE;

  // Allocate memory for int_value and set its value
  int64_t* int_value = calloc(1, sizeof(int64_t));
  assert(int_value != NULL && "Memory allocation failed for int_value");
  *int_value = value;
  dst.test_cond_value->int_value = int_value;
  return dst;
}

static
label_info_lst_t fill_kpm_label(void)
{
  label_info_lst_t label_item = {0};

  label_item.noLabel = ecalloc(1, sizeof(enum_value_e));
  *label_item.noLabel = TRUE_ENUM_VALUE;

  return label_item;
}

static
kpm_act_def_format_1_t fill_act_def_frm_1(ric_report_style_item_t const* report_item)
{
  assert(report_item != NULL);

  kpm_act_def_format_1_t ad_frm_1 = {0};

  size_t const sz = report_item->meas_info_for_action_lst_len;

  // [1, 65535]
  ad_frm_1.meas_info_lst_len = sz;
  ad_frm_1.meas_info_lst = calloc(sz, sizeof(meas_info_format_1_lst_t));
  assert(ad_frm_1.meas_info_lst != NULL && "Memory exhausted");

  for (size_t i = 0; i < sz; i++) 
  {
    meas_info_format_1_lst_t* meas_item = &ad_frm_1.meas_info_lst[i];
    // 8.3.9
    // Measurement Name
    meas_item->meas_type.type = NAME_MEAS_TYPE;
    meas_item->meas_type.name = copy_byte_array(report_item->meas_info_for_action_lst[i].name);

    // [1, 2147483647]
    // 8.3.11
    meas_item->label_info_lst_len = 1;
    meas_item->label_info_lst = ecalloc(1, sizeof(label_info_lst_t));
    meas_item->label_info_lst[0] = fill_kpm_label();
  }

  // 8.3.8 [0, 4294967295]
  ad_frm_1.gran_period_ms = period_ms;

  // 8.3.20 - OPTIONAL
  ad_frm_1.cell_global_id = NULL;

#if defined KPM_V2_03 || defined KPM_V3_00
  // [0, 65535]
  ad_frm_1.meas_bin_range_info_lst_len = 0;
  ad_frm_1.meas_bin_info_lst = NULL;
#endif

  return ad_frm_1;
}

static
kpm_act_def_t fill_report_style_4(ric_report_style_item_t const* report_item)
{
  assert(report_item != NULL);
  assert(report_item->act_def_format_type == FORMAT_4_ACTION_DEFINITION);

  kpm_act_def_t act_def = {.type = FORMAT_4_ACTION_DEFINITION};

  // Fill matching condition
  // [1, 32768]
  act_def.frm_4.matching_cond_lst_len = 1;
  act_def.frm_4.matching_cond_lst =
      calloc(act_def.frm_4.matching_cond_lst_len, sizeof(matching_condition_format_4_lst_t));
  assert(act_def.frm_4.matching_cond_lst != NULL && "Memory exhausted");
  // Filter connected UEs by S-NSSAI criteria
  test_cond_type_e const type = IsStat_TEST_COND_TYPE;  // CQI_TEST_COND_TYPE
  test_cond_e const condition = LESSTHAN_TEST_COND;     // GREATERTHAN_TEST_COND
  int const value = 40;
  act_def.frm_4.matching_cond_lst[0].test_info_lst = filter_predicate(type, condition, value);

  // Fill Action Definition Format 1
  // 8.2.1.2.1
  act_def.frm_4.action_def_format_1 = fill_act_def_frm_1(report_item);

  return act_def;
}

typedef kpm_act_def_t (*fill_kpm_act_def)(ric_report_style_item_t const* report_item);

static
fill_kpm_act_def get_kpm_act_def[END_RIC_SERVICE_REPORT] =
{
    NULL,
    NULL,
    NULL,
    fill_report_style_4,
    NULL,
};

static
kpm_sub_data_t gen_kpm_subs(kpm_ran_function_def_t const* ran_func)
{
  assert(ran_func != NULL);
  assert(ran_func->ric_event_trigger_style_list != NULL);

  kpm_sub_data_t kpm_sub = {0};

  // Generate Event Trigger
  assert(ran_func->ric_event_trigger_style_list[0].format_type == FORMAT_1_RIC_EVENT_TRIGGER);
  kpm_sub.ev_trg_def.type = FORMAT_1_RIC_EVENT_TRIGGER;
  kpm_sub.ev_trg_def.kpm_ric_event_trigger_format_1.report_period_ms = period_ms;

  // Generate Action Definition
  kpm_sub.sz_ad = 1;
  kpm_sub.ad = calloc(kpm_sub.sz_ad, sizeof(kpm_act_def_t));
  assert(kpm_sub.ad != NULL && "Memory exhausted");

  // Multiple Action Definitions in one SUBSCRIPTION message is not supported in this project
  // Multiple REPORT Styles = Multiple Action Definition = Multiple SUBSCRIPTION messages
  ric_report_style_item_t* const report_item = &ran_func->ric_report_style_list[0];
  ric_service_report_e const report_style_type = report_item->report_style_type;
  *kpm_sub.ad = get_kpm_act_def[report_style_type](report_item);

  return kpm_sub;
}

static
size_t find_sm_idx(sm_ran_function_t* rf, size_t sz, bool (*f)(sm_ran_function_t const*, int const),
                          int const id) 
{
  for (size_t i = 0; i < sz; i++) 
  {
    if (f(&rf[i], id))
      return i;
  }

  assert(0 != 0 && "SM ID could not be found in the RAN Function List");
  return 0;
}

//*************************************************************** *//
static
e2sm_rc_ctrl_hdr_frmt_1_t gen_rc_ctrl_hdr_frmt_1(ue_id_e2sm_t ue_id, uint32_t ric_style_type,
                                                         uint16_t ctrl_act_id)
{
  e2sm_rc_ctrl_hdr_frmt_1_t dst = {0};

  // 6.2.2.6
  dst.ue_id = cp_ue_id_e2sm(&ue_id);

  dst.ric_style_type = ric_style_type;
  dst.ctrl_act_id = ctrl_act_id;

  return dst;
}

static
e2sm_rc_ctrl_hdr_t gen_rc_ctrl_hdr(e2sm_rc_ctrl_hdr_e hdr_frmt, ue_id_e2sm_t ue_id,
                                           uint32_t ric_style_type, uint16_t ctrl_act_id) 
{
  e2sm_rc_ctrl_hdr_t dst = {0};

  if (hdr_frmt == FORMAT_1_E2SM_RC_CTRL_HDR) {
    dst.format = FORMAT_1_E2SM_RC_CTRL_HDR;
    dst.frmt_1 = gen_rc_ctrl_hdr_frmt_1(ue_id, ric_style_type, ctrl_act_id);
  } else 
  {
    assert(0 != 0 && "not implemented the fill func for this ctrl hdr frmt");
  }

  return dst;
}

static
void set_EUTRA_CGI(seq_ran_param_t* EUTRA_CGI, const char targetcell)
{
  // Input validation
  assert(EUTRA_CGI != NULL);
  assert(targetcell >= '0' && targetcell <= '9');

  // Validate flag_false is allocated
  if (EUTRA_CGI->ran_param_val.flag_false == NULL) {
    EUTRA_CGI->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
    assert(EUTRA_CGI->ran_param_val.flag_false != NULL && "Memory exhausted");
  }

  EUTRA_CGI->ran_param_val.flag_false->type = BIT_STRING_RAN_PARAMETER_VALUE;

  // Convert target cell to byte array
  byte_array_t target_ba = {0};
  target_ba.len = 1;
  target_ba.buf = malloc(sizeof(uint8_t));
  assert(target_ba.buf != NULL && "Memory exhausted");
  target_ba.buf[0] = targetcell;

  EUTRA_CGI->ran_param_val.flag_false->octet_str_ran.len = target_ba.len;
  EUTRA_CGI->ran_param_val.flag_false->octet_str_ran.buf = target_ba.buf;
}

static
void gen_Target_Primary_Cell_ID(seq_ran_param_t* Target_Primary_Cell_ID, char targetcell)
{
  // Target Primary Cell ID, STRUCTURE (len 1)

  Target_Primary_Cell_ID->ran_param_id = TARGET_PRIMARY_CELL_ID_8_4_4_1;
  Target_Primary_Cell_ID->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  Target_Primary_Cell_ID->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(Target_Primary_Cell_ID->ran_param_val.strct != NULL && "Memory exhausted");
  Target_Primary_Cell_ID->ran_param_val.strct->sz_ran_param_struct = 1;
  Target_Primary_Cell_ID->ran_param_val.strct->ran_param_struct = calloc(1, sizeof(seq_ran_param_t));
  assert(Target_Primary_Cell_ID->ran_param_val.strct->ran_param_struct != NULL && "Memory exhausted");

  // > CHOICE Target Cell, STRUCTURE (len 2)
  seq_ran_param_t* CHOICE_Target_Cell = &Target_Primary_Cell_ID->ran_param_val.strct->ran_param_struct[0];
  CHOICE_Target_Cell->ran_param_id = CHOICE_TARGET_CELL_8_4_4_1;
  CHOICE_Target_Cell->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  CHOICE_Target_Cell->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(CHOICE_Target_Cell->ran_param_val.strct != NULL && "Memory exhausted");
  CHOICE_Target_Cell->ran_param_val.strct->sz_ran_param_struct = 2;
  CHOICE_Target_Cell->ran_param_val.strct->ran_param_struct = calloc(2, sizeof(seq_ran_param_t));
  assert(CHOICE_Target_Cell->ran_param_val.strct->ran_param_struct != NULL && "Memory exhausted");

  // >>  NR Cell, STRUCTURE (len 1))
  seq_ran_param_t* NR_Cell = &CHOICE_Target_Cell->ran_param_val.strct->ran_param_struct[0];
  NR_Cell->ran_param_id = NR_CELL_8_4_4_1;
  NR_Cell->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  NR_Cell->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(NR_Cell->ran_param_val.strct != NULL && "Memory exhausted");
  NR_Cell->ran_param_val.strct->sz_ran_param_struct = 1;
  NR_Cell->ran_param_val.strct->ran_param_struct = calloc(1, sizeof(seq_ran_param_t));

  // >>> NR CGI, ELEMENT   NR CGI is usually written in the format: PLMN ID + NR Cell Identity.
  seq_ran_param_t* NR_CGI = &NR_Cell->ran_param_val.strct->ran_param_struct[0];
  NR_CGI->ran_param_id = NR_CGI_8_4_4_1;
  NR_CGI->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  NR_CGI->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(NR_CGI->ran_param_val.flag_false != NULL && "Memory exhausted");
  NR_CGI->ran_param_val.flag_false->type = BIT_STRING_RAN_PARAMETER_VALUE;
  // NR_CGI->ran_param_val.flag_false->int_ran=  TARGET_CELL;
  char nr_cgi_str[1] = {targetcell};

  byte_array_t nr_cgi = cp_str_to_ba(nr_cgi_str);
  NR_CGI->ran_param_val.flag_false->octet_str_ran.len = nr_cgi.len;
  NR_CGI->ran_param_val.flag_false->octet_str_ran.buf = nr_cgi.buf;

  // >>E-UTRA Cell, STRUCTURE (len 1)
  seq_ran_param_t* EUTRA_Cell = &CHOICE_Target_Cell->ran_param_val.strct->ran_param_struct[1];
  EUTRA_Cell->ran_param_id = EUTRA_CELL_8_4_4_1;
  EUTRA_Cell->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  EUTRA_Cell->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(EUTRA_Cell->ran_param_val.strct != NULL && "Memory exhausted");
  EUTRA_Cell->ran_param_val.strct->sz_ran_param_struct = 1;
  EUTRA_Cell->ran_param_val.strct->ran_param_struct = calloc(1, sizeof(seq_ran_param_t));

  // >>>E-UTRA CGI, ELEMENT  The E-UTRA CGI is typically written in the format: PLMN ID + E-UTRAN Cell Identity.
  seq_ran_param_t* EUTRA_CGI = &EUTRA_Cell->ran_param_val.strct->ran_param_struct[0];
  EUTRA_CGI->ran_param_id = EUTRA_CGI_8_4_4_1;
  EUTRA_CGI->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  EUTRA_CGI->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(EUTRA_CGI->ran_param_val.flag_false != NULL && "Memory exhausted");
  EUTRA_CGI->ran_param_val.flag_false->type = BIT_STRING_RAN_PARAMETER_VALUE;

  set_EUTRA_CGI(EUTRA_CGI, targetcell);

  // char eUTRA_cgi_str [2] ;
  // eUTRA_cgi_str[0] = targetcell;
  // eUTRA_cgi_str [1] = '\0';

  // byte_array_t eUTRA_cgi = cp_str_to_ba(eUTRA_cgi_str);
  // EUTRA_CGI->ran_param_val.flag_false->octet_str_ran.len = eUTRA_cgi.len;
  // EUTRA_CGI->ran_param_val.flag_false->octet_str_ran.buf = eUTRA_cgi.buf;
  return;
}

static
void gen_List_of_PDU_sessions_for_handover(seq_ran_param_t* List_PDU_sessions_ho)
{
  int num_PDU_session = 1;

  // List of PDU sessions for handover, LIST (len 1)
  List_PDU_sessions_ho->ran_param_id = LIST_OF_PDU_SESSIONS_FOR_HANDOVER_8_4_4_1;
  List_PDU_sessions_ho->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  List_PDU_sessions_ho->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(List_PDU_sessions_ho->ran_param_val.lst != NULL && "Memory exhausted");
  List_PDU_sessions_ho->ran_param_val.lst->sz_lst_ran_param = num_PDU_session;
  List_PDU_sessions_ho->ran_param_val.lst->lst_ran_param = calloc(num_PDU_session, sizeof(lst_ran_param_t));
  assert(List_PDU_sessions_ho->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  // > PDU session Item for handover, STRUCTURE (len 2)
  lst_ran_param_t* PDU_session_item = &List_PDU_sessions_ho->ran_param_val.lst->lst_ran_param[0];
  PDU_session_item->ran_param_struct.sz_ran_param_struct = 2;
  PDU_session_item->ran_param_struct.ran_param_struct = calloc(2, sizeof(seq_ran_param_t));
  assert(PDU_session_item->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  // >> PDU Session ID, ELEMENT
  seq_ran_param_t* PDU_Session_ID = &PDU_session_item->ran_param_struct.ran_param_struct[0];
  PDU_Session_ID->ran_param_id = PDU_SESSION_ID_8_4_4_1;
  PDU_Session_ID->ran_param_val.type = ELEMENT_KEY_FLAG_TRUE_RAN_PARAMETER_VAL_TYPE;
  PDU_Session_ID->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(PDU_Session_ID->ran_param_val.flag_false != NULL && "Memory exhausted");
  PDU_Session_ID->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;

  // Use enum for PDU Session ID
  char pduid_str[2];
  snprintf(pduid_str, sizeof(pduid_str), "%d", PDU_SESSION_ID_5);
  byte_array_t pduid = cp_str_to_ba(pduid_str);
  PDU_Session_ID->ran_param_val.flag_false->octet_str_ran.len = pduid.len;
  PDU_Session_ID->ran_param_val.flag_false->octet_str_ran.buf = pduid.buf;

  // >> List of QoS flows in the PDU session, LIST (len 1)
  seq_ran_param_t* List_of_QoS_flows = &PDU_session_item->ran_param_struct.ran_param_struct[1];
  List_of_QoS_flows->ran_param_id = LIST_OF_QOS_FLOWS_IN_THE_PDU_SESSION_8_4_4_1;
  List_of_QoS_flows->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  List_of_QoS_flows->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(List_of_QoS_flows->ran_param_val.lst != NULL && "Memory exhausted");
  List_of_QoS_flows->ran_param_val.lst->sz_lst_ran_param = 1;
  List_of_QoS_flows->ran_param_val.lst->lst_ran_param = calloc(1, sizeof(lst_ran_param_t));
  assert(List_of_QoS_flows->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  // >>> QoS flow Item, STRUCTURE (len 1)
  lst_ran_param_t* QoS_flow_Item = &List_of_QoS_flows->ran_param_val.lst->lst_ran_param[0];
  QoS_flow_Item->ran_param_struct.sz_ran_param_struct = 1;
  QoS_flow_Item->ran_param_struct.ran_param_struct = calloc(1, sizeof(seq_ran_param_t));
  assert(QoS_flow_Item->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  // >>>> QoS Flow Identifier, ELEMENT
  seq_ran_param_t* QoS_Flow_Id = &QoS_flow_Item->ran_param_struct.ran_param_struct[0];
  QoS_Flow_Id->ran_param_id = QOS_FLOW_IDENTIFIER_8_4_4_1;
  QoS_Flow_Id->ran_param_val.type = ELEMENT_KEY_FLAG_TRUE_RAN_PARAMETER_VAL_TYPE;
  QoS_Flow_Id->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(QoS_Flow_Id->ran_param_val.flag_false != NULL && "Memory exhausted");
  QoS_Flow_Id->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;

  // Use enum for QoS Flow ID
  char qosid_str[3];
  snprintf(qosid_str, sizeof(qosid_str), "%d", QOS_FLOW_ID_1);
  byte_array_t qosid = cp_str_to_ba(qosid_str);
  QoS_Flow_Id->ran_param_val.flag_false->octet_str_ran.len = qosid.len;
  QoS_Flow_Id->ran_param_val.flag_false->octet_str_ran.buf = qosid.buf;

  return;
}

static
void gen_List_of_DRBs_for_handover(seq_ran_param_t* List_DRBs_ho)
{
  int num_DRBs = 1;
  // List of DRBs for handover, LIST (len 1)
  List_DRBs_ho->ran_param_id = LIST_OF_DRBS_FOR_HANDOVER_8_4_4_1;
  List_DRBs_ho->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  List_DRBs_ho->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(List_DRBs_ho->ran_param_val.lst != NULL && "Memory exhausted");
  List_DRBs_ho->ran_param_val.lst->sz_lst_ran_param = num_DRBs;
  List_DRBs_ho->ran_param_val.lst->lst_ran_param = calloc(num_DRBs, sizeof(lst_ran_param_t));
  assert(List_DRBs_ho->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  // > DRB item for handover, STRUCTURE (len 2)
  lst_ran_param_t* DRB_item_ho = (lst_ran_param_t*)&List_DRBs_ho->ran_param_val.strct->ran_param_struct[0];

  DRB_item_ho->ran_param_struct.sz_ran_param_struct = 2;
  DRB_item_ho->ran_param_struct.ran_param_struct = calloc(2, sizeof(seq_ran_param_t));
  assert(DRB_item_ho->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  // >> DRB ID, ELEMENT
  seq_ran_param_t* DRB_ID = &DRB_item_ho->ran_param_struct.ran_param_struct[0];
  DRB_ID->ran_param_id = DRB_ID_8_4_4_1;
  DRB_ID->ran_param_val.type = ELEMENT_KEY_FLAG_TRUE_RAN_PARAMETER_VAL_TYPE;
  DRB_ID->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(DRB_ID->ran_param_val.flag_false != NULL && "Memory exhausted");
  DRB_ID->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  char DRB_ID_str[] = "3";
  byte_array_t drpID = cp_str_to_ba(DRB_ID_str);
  DRB_ID->ran_param_val.flag_false->octet_str_ran.len = drpID.len;
  DRB_ID->ran_param_val.flag_false->octet_str_ran.buf = drpID.buf;

  // >> List of QoS flows in the DRB, LIST (len 1)
  seq_ran_param_t* List_of_QoS_flows = &DRB_item_ho->ran_param_struct.ran_param_struct[1];  //////.....//////
  List_of_QoS_flows->ran_param_id = LIST_OF_QOS_FLOWS_IN_THE_DRB_8_4_4_1;
  List_of_QoS_flows->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  List_of_QoS_flows->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(List_of_QoS_flows->ran_param_val.lst != NULL && "Memory exhausted");
  List_of_QoS_flows->ran_param_val.lst->sz_lst_ran_param = 1;
  List_of_QoS_flows->ran_param_val.lst->lst_ran_param = calloc(1, sizeof(lst_ran_param_t));
  assert(List_of_QoS_flows->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  // >>>QoS flow Item, STRUCTURE (len 1)
  lst_ran_param_t* QoS_flow_Item = &List_of_QoS_flows->ran_param_val.lst->lst_ran_param[0];
  QoS_flow_Item->ran_param_struct.sz_ran_param_struct = 1;
  QoS_flow_Item->ran_param_struct.ran_param_struct = calloc(1, sizeof(seq_ran_param_t));
  assert(QoS_flow_Item->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  // >>>>QoS Flow Identifier, ELEMENT
  seq_ran_param_t* QoS_Flow_Id = &QoS_flow_Item->ran_param_struct.ran_param_struct[0];
  QoS_Flow_Id->ran_param_id = QOS_FLOW_IDENTIFIER_8_4_4_1;
  QoS_Flow_Id->ran_param_val.type = ELEMENT_KEY_FLAG_TRUE_RAN_PARAMETER_VAL_TYPE;
  QoS_Flow_Id->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(QoS_Flow_Id->ran_param_val.flag_false != NULL && "Memory exhausted");
  QoS_Flow_Id->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  char QFI_str[] = "10";
  byte_array_t QFI = cp_str_to_ba(QFI_str);
  QoS_Flow_Id->ran_param_val.flag_false->octet_str_ran.len = QFI.len;
  QoS_Flow_Id->ran_param_val.flag_false->octet_str_ran.buf = QFI.buf;

  return;
}

static
void gen_List_of_Secondary_cells_to_be_setup(seq_ran_param_t* List_num_2ndCells)
{
  int num_2ndCells = 1;
  // List of Secondary cells to be setup, LIST (len 1)
  List_num_2ndCells->ran_param_id = LIST_OF_SECONDARY_CELLS_TO_BE_SETUP_8_4_4_1;
  List_num_2ndCells->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  List_num_2ndCells->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(List_num_2ndCells->ran_param_val.lst != NULL && "Memory exhausted");
  List_num_2ndCells->ran_param_val.lst->sz_lst_ran_param = num_2ndCells;
  List_num_2ndCells->ran_param_val.lst->lst_ran_param = calloc(num_2ndCells, sizeof(lst_ran_param_t));
  assert(List_num_2ndCells->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  // >Secondary cell Item to be setup, STRUCTURE (len 1)
  lst_ran_param_t* secCell_item = (lst_ran_param_t*)&List_num_2ndCells->ran_param_val.strct->ran_param_struct[0];

  secCell_item->ran_param_struct.sz_ran_param_struct = 1;
  secCell_item->ran_param_struct.ran_param_struct = calloc(1, sizeof(seq_ran_param_t));
  assert(secCell_item->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  // >>Secondary cell ID, ELEMENT
  seq_ran_param_t* secCell_Id = &secCell_item->ran_param_struct.ran_param_struct[0];
  secCell_Id->ran_param_id = SECONDARY_CELL_ID_8_4_4_1;
  secCell_Id->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  secCell_Id->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(secCell_Id->ran_param_val.flag_false != NULL && "Memory exhausted");
  secCell_Id->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  char cellID_str[] = "0";
  byte_array_t QFI = cp_str_to_ba(cellID_str);
  secCell_Id->ran_param_val.flag_false->octet_str_ran.len = QFI.len;
  secCell_Id->ran_param_val.flag_false->octet_str_ran.buf = QFI.buf;

  return;
}

static
e2sm_rc_ctrl_msg_frmt_1_t gen_rc_ctrl_msg_frmt_1_Handover_Control(char targetcell)
{
  e2sm_rc_ctrl_msg_frmt_1_t dst = {0};
  // 8.4.4.1

  // Target Primary Cell ID, STRUCTURE (len 1)
  // > CHOICE Target Cell, STRUCTURE (len 2)
  // >>  NR Cell, STRUCTURE (len 1))
  // >>> NR CGI, ELEMENT
  // >>E-UTRA Cell, STRUCTURE (len 1)
  // >>>E-UTRA CGI, ELEMENT

  // List of PDU sessions for handover, LIST (len 1)
  // >PDU session Item for handover, STRUCTURE (len 2)
  // >>PDU Session ID, ELEMENT
  // >>List of QoS flows in the PDU session, LIST (len 1)
  // >>>QoS flow Item, STRUCTURE (len 1)
  // >>>>QoS Flow Identifier, ELEMENT

  // List of DRBs for handover, LIST (len 1)
  // > DRB item for handover, STRUCTURE (len 2)
  // >> DRB ID, ELEMENT
  // >> List of QoS flows in the DRB, LIST (len 1)
  // >>> QoS flow Item, STRUCTURE (len 1)
  // >>>> QoS flow Identifier, ELEMENT

  // List of Secondary cells to be setup, LIST (len 1)
  // >Secondary cell Item to be setup, STRUCTURE (len 1)
  // >>Secondary cell ID, ELEMENT

  dst.sz_ran_param = 4;
  dst.ran_param = calloc(4, sizeof(seq_ran_param_t));
  assert(dst.ran_param != NULL && "Memory exhausted");

  gen_Target_Primary_Cell_ID(&dst.ran_param[0], targetcell);
  gen_List_of_PDU_sessions_for_handover(&dst.ran_param[1]);
  gen_List_of_DRBs_for_handover(&dst.ran_param[2]);
  gen_List_of_Secondary_cells_to_be_setup(&dst.ran_param[3]);

  return dst;
}

static
e2sm_rc_ctrl_msg_frmt_1_t gen_rc_ctrl_msg_frmt_1_cell_trigger(char targetcell)
{
  e2sm_rc_ctrl_msg_frmt_1_t dst = {0};
  // 8.4.4.1

  // Target Primary Cell ID, STRUCTURE (len 1)
  // > CHOICE Target Cell, STRUCTURE (len 2)
  // >>  NR Cell, STRUCTURE (len 1))
  // >>> NR CGI, ELEMENT
  // >>E-UTRA Cell, STRUCTURE (len 1)
  // >>>E-UTRA CGI, ELEMENT
  dst.sz_ran_param = 1;
  dst.ran_param = calloc(4, sizeof(seq_ran_param_t));
  assert(dst.ran_param != NULL && "Memory exhausted");

  gen_Target_Primary_Cell_ID(&dst.ran_param[0], targetcell);
  return dst;
}

static
e2sm_rc_ctrl_msg_t gen_handover_rc_ctrl_msg(e2sm_rc_ctrl_msg_e msg_frmt, uint8_t targetcell)
{
  e2sm_rc_ctrl_msg_t dst = {0};

  if (msg_frmt == FORMAT_1_E2SM_RC_CTRL_MSG) {
    dst.format = msg_frmt;
    dst.frmt_1 = gen_rc_ctrl_msg_frmt_1_Handover_Control(targetcell);
  } else 
  {
    assert(0 != 0 && "not implemented the fill func for this ctrl msg frmt");
  }

  return dst;
}

static
e2sm_rc_ctrl_msg_t gen_cell_trigger_rc_ctrl_msg(e2sm_rc_ctrl_msg_e msg_frmt, char targetcell)
{
  e2sm_rc_ctrl_msg_t dst = {0};

  if (msg_frmt == FORMAT_1_E2SM_RC_CTRL_MSG) {
    dst.format = msg_frmt;
    dst.frmt_1 = gen_rc_ctrl_msg_frmt_1_cell_trigger(targetcell);
  } else 
  {
    assert(0 != 0 && "not implemented the fill func for this ctrl msg frmt");
  }

  return dst;
}

static
ue_id_e2sm_t gen_rc_ue_id(ue_id_e2sm_e type, int ueid)
{
  ue_id_e2sm_t ue_id = {0};
  if (type == GNB_UE_ID_E2SM) {
    ue_id.type = GNB_UE_ID_E2SM;
    ue_id.gnb.ran_ue_id = (uint64_t*)malloc(sizeof(uint64_t));
    *(ue_id.gnb.ran_ue_id) = ueid;
  } else 
  {
    assert(0 != 0 && "not supported UE ID type");
  }
  return ue_id;
}

static
bool eq_sm(sm_ran_function_t const* elem, int const id)
{
  if (elem->id == id)
    return true;

  return false;
}

static
void forEachCell(Callback targetCellFinding, Callback cbHOAction, Callback cbSwitchOffAction, callback_data_t data) 
{
  static bool processed_cells[MAX_REGISTERED_CELLS] = {false};
  static const int SHUTDOWN_TIMEOUT_SEC = 30; 

  printf("\n=== Evaluating Cells for Energy Saving ===\n");

  // First pass: Mark cells that are candidates for shutdown
  for (int i = 0; i < MAX_REGISTERED_CELLS; i++) 
  {
    if (cells_sinr_map[i].sinrMap != NULL && 
        cells_sinr_map[i].is_registered && 
        !processed_cells[i] &&
        !cells_sinr_map[i].sinrMap->pending_shutdown) {
      
      struct SINR_Map* cell = cells_sinr_map[i].sinrMap;
      
      // Check if cell meets shutdown criteria (low utilization, etc)
      if (cell->numOfConnectedUEs <= 1) { // Example criteria
        cell->pending_shutdown = true;
        cell->shutdown_start_time = time(NULL);
        printf("Cell %d marked for shutdown\n", cell->cellID);
      }
    }
  }

  // Second pass: Process handovers and shutdowns
  for (int i = 0; i < MAX_REGISTERED_CELLS; i++) 
  {
    if (cells_sinr_map[i].sinrMap != NULL && 
        cells_sinr_map[i].is_registered && 
        !processed_cells[i]) {
      
      struct SINR_Map* cell = cells_sinr_map[i].sinrMap;
      
      if (!cell->pending_shutdown) {
        continue; // Skip cells not marked for shutdown
      }

      printf(" Cell %d  meeting the Action Defination Condition\n", cell->cellID);

      size_t handovers_needed = 0;
      size_t handovers_completed = 0;

      // Check each UE in this cell
      for (int j = 0; j < MAX_REGISTERED_UES; j++) {
        if (cell->connectedUEs[j].is_available && 
            cell->connectedUEs[j].neighCells != NULL &&
            !cell->connectedUEs[j].handover_in_progress) {

          callback_data_t ue_data = {
            .nodes = data.nodes,
            .neighCells = cell->connectedUEs[j].neighCells,
            .ueID = cell->connectedUEs[j].ueID,
            .frmCurntCell = cell->cellID
          };

          // Find target cell, excluding cells marked for shutdown
          uint8_t target = targetCellFinding(ue_data);
          
          if (target != 0) {
            ue_data.toTargetCell = target;

            // Trigger handover
            if (cbHOAction(ue_data)) {
              handovers_needed++;
              cell->connectedUEs[j].handover_in_progress = true;
              handovers_completed++;
            }
          }
        }
      }

      // Check if we can proceed with shutdown
      time_t current_time = time(NULL);
      bool timeout_reached = (current_time - cell->shutdown_start_time) > SHUTDOWN_TIMEOUT_SEC;
      
      if ((handovers_needed > 0 && handovers_needed == handovers_completed) || 
          (timeout_reached && handovers_completed == cell->numOfConnectedUEs)) {
        
        printf("All handovers complete (%ld/%ld) or timeout reached for cell %d\n",
               handovers_completed, handovers_needed, cell->cellID);
        
        data.frmCurntCell = cell->cellID;
        if (cbSwitchOffAction(data)) {
          // Clean up cell data structures
          if (cell->connectedUEs != NULL) {
            for (int j = 0; j < MAX_REGISTERED_UES; j++) {
              if (cell->connectedUEs[j].neighCells != NULL) {
                free(cell->connectedUEs[j].neighCells);
                cell->connectedUEs[j].neighCells = NULL;
              }
            }
            free(cell->connectedUEs);
            cell->connectedUEs = NULL;
          }
          
          free(cells_sinr_map[i].sinrMap);
          cells_sinr_map[i].sinrMap = NULL;
          cells_sinr_map[i].is_registered = false;
          processed_cells[i] = true;
          
          printf("Cell %d switched off and cleaned up\n", cell->cellID);
        }
      }
    }
  }
}

// void doHandoverAction(const e2_node_arr_xapp_t * nodes, const int ueID, const uint8_t frmCurntCell, const uint8_t
// toTargetCell) {
static
uint16_t doHandoverAction(callback_data_t data) 
{
  char trgtCell = '0' + data.toTargetCell;
  printf("[xApp]: data.toTargetCell= %d ..\n", data.toTargetCell);

  if (!(trgtCell > '0' && trgtCell <= '9')) {
    printf("[xApp]: Invalid target cell %c\n", trgtCell);
    return 0;
  }

  rc_ctrl_req_data_t rc_ctrl = {0};
  ue_id_e2sm_t ue_id_1 = gen_rc_ue_id(GNB_UE_ID_E2SM, data.ueID);

  rc_ctrl.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, ue_id_1, CONNECTED_MODE_MOBILITY,
                                HANDOVER_CONTROL_7_6_4_1);
  rc_ctrl.msg = gen_handover_rc_ctrl_msg(FORMAT_1_E2SM_RC_CTRL_MSG, trgtCell);

  printf("[xApp]: Send Handover Control message to move IMSI %d from cellId %d to target cellId %c \n", data.ueID,
         data.frmCurntCell, trgtCell);

  bool handover_sent = false;
  for (size_t i = ho_node_idx; i < ho_node_idx + 1 && i < (*data.nodes).len; ++i) 
  {
    sm_ans_xapp_t ans = control_sm_xapp_api(&(*data.nodes).n[i].id, SM_RC_ID, &rc_ctrl);

    if (ans.success) {
      handover_sent = true;
      printf("[xApp]: Handover request sent successfully to node %zu\n", i);
    }
  }

  /* ONE_SHOT_EXIT: skip free, one-shot xApp exits right after */
  return handover_sent ? 1 : 0;
}

static
uint16_t switchOffCurrentCell(callback_data_t data)
{
  rc_ctrl_req_data_t rc_ctrl = {0};
  ue_id_e2sm_t ue_id = gen_rc_ue_id(GNB_UE_ID_E2SM, data.ueID);

  rc_ctrl.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, ue_id, ENERGY_STATE, CELL_OFF);
  char frmCurentCell = '0' + data.frmCurntCell;
  rc_ctrl.msg = gen_cell_trigger_rc_ctrl_msg(FORMAT_1_E2SM_RC_CTRL_MSG, frmCurentCell);

  printf("[xApp]: Send switch off Control message to switch off cell %d\n", data.frmCurntCell);
  control_sm_xapp_api(&(*data.nodes).n[0].id, SM_RC_ID, &rc_ctrl);

  free_rc_ctrl_req_data(&rc_ctrl);

  return 0;
}

#ifndef SM_KPM_ID
#define SM_KPM_ID 2  /* KPM RAN function id (ns-3 KPM_E2functionID) */
#endif

/* =====================================================================
 * JamGuard xApp: closed-loop jamming countermeasure over E2
 *   KPM report style 4 (100 ms): serving + neighbour L3 SINR per UE
 *   detect -> localize -> mitigate (NR handover, or move the UE data
 *   path to the LTE anchor) -> probe -> return to NR.
 *   Actuator: RC Connected_Mode_Mobility / Handover_Control only.
 *     target cell 1 (LTE anchor)  : move UE data path to LTE
 *     target cell >= 2 (NR)       : NR handover, or return from LTE
 *   Parameters come from environment variables JG_* (see below).
 *   The helper functions above main() are those of xapp_manual_ho.c.
 * ===================================================================== */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

#define JG_MAX_UE 128
#define JG_MAX_NODES 8
#define JG_MAX_NB 8
#define JG_MAX_ACT 64

enum { JG_NR = 0, JG_LTE = 1, JG_PROBE = 2 };

typedef struct {
  int known, cell, last_nr_cell, state;
  double sinr, base;
  int base_n;
  long upd, eval, nb_round, cool_until, t_evac, probe_since;
  int nb_n, nb_cell[JG_MAX_NB];
  double nb_sinr[JG_MAX_NB];
  int deg_cnt, ok_cnt, bad_cnt, stab;
  double jam_w;
  int has_pos;
  double x, y;
  double nb_base[16]; int nb_base_n[16];          /* JGV3 neighbour baselines            */
  int prev_cell, pass_ok; long ho_round, pass_r;  /* JGV3 anti ping-pong, passive recovery */
  double rsrp; long rsrp_r;                       /* JGTRI serving RSRP-like power [dBm]   */
  double nb_rsrp[16]; long nb_rsrp_r[16];         /* JGTRI2 neighbour RSRP per cell [dBm]  */
  double wj[16]; int wn; double wx, wy;           /* JGTRI current 1-s window              */
} jg_ue_t;

typedef struct { int imsi, from, to; } jg_act_t;

static jg_ue_t jg_ue[JG_MAX_UE];
static long jg_node_cnt[JG_MAX_NODES];
static int jg_node_cell[JG_MAX_NODES];
static long jg_round = 0;
static volatile sig_atomic_t jg_stop = 0;
static e2_node_arr_xapp_t jg_nodes;
static FILE* jg_log = NULL;
static FILE* jg_kpm = NULL;   /* JG_KPM_DUMP=file : every UE-level KPM received over E2 */

/* parameters: environment variable [default] */
static int    P_POLICY   = 2;     /* JG_POLICY   0 monitor only, 1 reactive, 2 localization-aware */
static double P_S_LOW    = 0.0;   /* JG_S_LOW    dB: degraded if serving SINR below this ...      */
static double P_DROP     = 8.0;   /* JG_DROP     dB: ... and this far below the UE's own baseline */
static int    P_P        = 3;     /* JG_P        persistence in reports (1 report = 100 ms)       */
static int    P_K        = 2;     /* JG_K        degraded UEs needed to declare jamming           */
static double P_S_OK     = 5.0;   /* JG_S_OK     dB: SINR counted as recovered                    */
static double P_HYST     = 3.0;   /* JG_HYST     dB: NR neighbour must beat serving by this       */
static int    P_HOLD     = 20;    /* JG_HOLD     reports on LTE before the first probe            */
static int    P_HOLD_MAX = 160;   /* JG_HOLD_MAX upper limit of the probe back-off                */
static int    P_COOL     = 10;    /* JG_COOL     reports between two actions on the same UE       */
static int    P_FRESH    = 3;     /* JG_FRESH    reports: older measurements are ignored          */
static double P_R_MIN    = 30.0;  /* JG_R_MIN    m: smallest radius of the jamming zone           */
static double P_R_MARGIN = 20.0;  /* JG_R_MARGIN m: added to the farthest degraded UE             */
static int    P_SINR_3GPP = 0;    /* JG_SINR_3GPP 1: KPM values are 3GPP-encoded (v/2 - 23 dB)    */
static int    P_LTE_CELL = 1;     /* JG_LTE_CELL cell id of the LTE anchor                        */
static long   P_ROUNDS   = 0;     /* JG_ROUNDS   stop after this many reports (0: until Ctrl-C)   */
static const char* P_POS = NULL;  /* JG_POS      UE position file (positioning service)           */
static int    P_PC[3]    = {0, 1, 2}; /* JG_POS_COLS columns of imsi,x,y in that file             */
static const char* P_LOG = "jamguard_log.csv"; /* JG_LOG action log for analysis and dashboard  */
static int    P_RET_GUARD = 1;    /* JG_RET_GUARD 1: return a UE to NR only when its NR SINR >= S_ok */
static const char* P_CLOCK = NULL; /* JG_CLOCK file whose last line starts with the ns-3 time [s] */
/* JamGuard v2: slice-aware mitigation/recovery, baselines, cell-level E2 control, latency log */
static int    P_SLICE = 0;          /* JG_SLICE 1: slice-aware mitigation (p3)                        */
static int    P_SREC = 0;           /* JG_SREC  1: slice-aware recovery + sentinel check (p4)         */
static int    P_LTE_EMBB_MAX = 2;   /* JG_LTE_EMBB_MAX eMBB UEs allowed on the LTE anchor at once     */
static double P_EMBB_Q = 0.5;       /* JG_EMBB_Q eMBB max ratio in NR cells that serve critical UEs   */
static double P_CRIT_MARGIN = 5.0;  /* JG_CRIT_MARGIN dB above S_ok before a critical UE leaves LTE   */
static int    P_CRIT_WAIT = 10;     /* JG_CRIT_WAIT reports after PROBE_OK before critical UEs return  */
static int    P_CRIT_STAB = 5;      /* JG_CRIT_STAB consecutive good reports of a critical UE          */
static double P_B2_Q = 0.2;         /* JG_B2_Q eMBB max ratio of baseline B2 (policy 5)               */
static int    P_B1_MCS = 2;         /* JG_B1_MCS DL MCS cap of baseline B1 (policy 6)                 */
static double P_CLIP = 0;          /* JGV3 JG_SINR_CLIP dB, 0 = off                                  */
static double P_PRO_MAX = 0;       /* JGV3 JG_PRO_MAX   proactive evacuation only below this SINR     */
static int    P_MLINK = 0;         /* JGV3 JG_MLINK     multi-link consistency test                    */
static int    P_LOC = 0;           /* JGV3 JG_LOC       1: SINR-weighted, smoothed localization        */
static int    P_PP = 0;            /* JGV3 JG_PP_HOLD   reports without NR handover back to prev cell  */
static int    P_PASSIVE = 0;       /* JGV3 JG_PASSIVE   1 passive + probes, 2 passive only             */
static int    P_PASS_N = 5;        /* JGV3 JG_PASS_N                                                   */
static double P_PASS_MARGIN = 5.0; /* JGV3 JG_PASS_MARGIN dB                                           */
static double jg_lsw = 0, jg_lsx = 0, jg_lsy = 0; /* JGV3 smoothed localization sums                 */
/* JGTRI: interference-power trilateration (JG_LOC=2) */
static double P_NOISE_DBM = -92.0;  /* JG_NOISE_DBM -174 + 10log10(20 MHz) + NF 9 dB                    */
static double P_INR_DB = 6.0;       /* JG_INR_DB    window kept if J^/N >= this                          */
static int    P_TRI_MIN = 8;        /* JGTRI2 JG_TRI_MIN observations before the fit is used  */
static int    P_TRI_LTE = 1;        /* JGTRI2 JG_TRI_LTE  keep evacuated UEs as observers     */
static int    P_TRI_UMIN = 0;       /* JGTRIU JG_TRI_UMIN distinct UEs before the fit is used (0 = off) */
static int    P_LOC_WIN = 0;        /* JG_LOC_WIN   0: all windows since the alarm, k: last k windows    */
static double P_AREA_MIN = 0.0, P_AREA_MAX = 1000.0; /* JG_AREA_MIN / JG_AREA_MAX search area [m]      */
#define JG_TRI_MAX 400
static double jg_tx[JG_TRI_MAX], jg_ty[JG_TRI_MAX], jg_tj[JG_TRI_MAX]; static long jg_tw[JG_TRI_MAX];
static int jg_tn = 0, jg_tri_ok = 0; static long jg_twin = 0;
static long   P_POLL_US = 20000;    /* JG_POLL_US period of the decision loop                         */
#define JG_MAX_CELL 16
static int    jg_slice[JG_MAX_UE];          /* imsi -> slice (0 eMBB), from JG_SLICES                 */
static int    jg_cell_seen[JG_MAX_CELL];    /* NR cells seen as serving cells in KPM                  */
static double jg_cap_now[JG_MAX_CELL];      /* cell -> eMBB ratio requested (1 = no cap)              */
static int    jg_mcs_now[JG_MAX_CELL];      /* cell -> MCS cap requested (-1 = none)                  */
static double jg_b2q = 1.0;
static long   jg_probe_ok_r = -1000;
static FILE*  jg_lat = NULL;                /* JG_LAT latency log                                     */
static uint64_t jg_kpm_us = 0;              /* wall clock of the last KPM indication                  */
typedef struct { int kind, cell, slice; double val; } jg_cact_t;   /* kind 0 slice quota, 1 MCS cap */
static jg_cact_t jg_cq[32];
static int jg_ncq = 0;
static void jg_cadd(int kind, int cell, int slice, double val)
{
  if (jg_ncq >= 32) return;
  jg_cq[jg_ncq].kind = kind; jg_cq[jg_ncq].cell = cell; jg_cq[jg_ncq].slice = slice; jg_cq[jg_ncq].val = val;
  jg_ncq++;
}

/* controller state */
static int jg_alarm = 0, jg_alarm_cnt = 0, jg_quiet = 0, jg_have_est = 0, jg_returning = 0, jg_probe = -1;
static double jg_ex = 0, jg_ey = 0, jg_er = 0;
static long jg_hold = 20, jg_next_probe = 0;

static double jg_envd(const char* k, double d) { const char* v = getenv(k); return v ? atof(v) : d; }
static double jg_clamp(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }
static double jg_sqrt(double v)
{
  if (v <= 0) return 0;
  double x = v > 1 ? v : 1;
  for (int i = 0; i < 60; i++) x = 0.5 * (x + v / x);
  return x;
}

static void jg_params(void)
{
  P_POLICY    = (int)jg_envd("JG_POLICY", P_POLICY);
  P_S_LOW     = jg_envd("JG_S_LOW", P_S_LOW);
  P_DROP      = jg_envd("JG_DROP", P_DROP);
  P_P         = (int)jg_envd("JG_P", P_P);
  P_K         = (int)jg_envd("JG_K", P_K);
  P_S_OK      = jg_envd("JG_S_OK", P_S_OK);
  P_HYST      = jg_envd("JG_HYST", P_HYST);
  P_HOLD      = (int)jg_envd("JG_HOLD", P_HOLD);
  P_HOLD_MAX  = (int)jg_envd("JG_HOLD_MAX", P_HOLD_MAX);
  P_COOL      = (int)jg_envd("JG_COOL", P_COOL);
  P_FRESH     = (int)jg_envd("JG_FRESH", P_FRESH);
  P_R_MIN     = jg_envd("JG_R_MIN", P_R_MIN);
  P_R_MARGIN  = jg_envd("JG_R_MARGIN", P_R_MARGIN);
  P_SINR_3GPP = (int)jg_envd("JG_SINR_3GPP", P_SINR_3GPP);
  P_LTE_CELL  = (int)jg_envd("JG_LTE_CELL", P_LTE_CELL);
  P_ROUNDS    = (long)jg_envd("JG_ROUNDS", 0);
  P_POS       = getenv("JG_POS");
  const char* pc = getenv("JG_POS_COLS");
  if (pc) sscanf(pc, "%d,%d,%d", &P_PC[0], &P_PC[1], &P_PC[2]);
  if (getenv("JG_LOG")) P_LOG = getenv("JG_LOG");
  P_RET_GUARD = (int)jg_envd("JG_RET_GUARD", P_RET_GUARD);
  P_CLOCK = getenv("JG_CLOCK");
  P_SLICE        = (int)jg_envd("JG_SLICE", P_SLICE);
  P_SREC         = (int)jg_envd("JG_SREC", P_SREC);
  P_LTE_EMBB_MAX = (int)jg_envd("JG_LTE_EMBB_MAX", P_LTE_EMBB_MAX);
  P_EMBB_Q       = jg_envd("JG_EMBB_Q", P_EMBB_Q);
  P_CRIT_MARGIN  = jg_envd("JG_CRIT_MARGIN", P_CRIT_MARGIN);
  P_CRIT_WAIT    = (int)jg_envd("JG_CRIT_WAIT", P_CRIT_WAIT);
  P_CRIT_STAB    = (int)jg_envd("JG_CRIT_STAB", P_CRIT_STAB);
  P_B2_Q         = jg_envd("JG_B2_Q", P_B2_Q);
  P_B1_MCS       = (int)jg_envd("JG_B1_MCS", P_B1_MCS);
  P_POLL_US      = (long)jg_envd("JG_POLL_US", P_POLL_US);
  P_CLIP = jg_envd("JG_SINR_CLIP", P_CLIP);  P_PRO_MAX = jg_envd("JG_PRO_MAX", P_PRO_MAX);   /* JGV3 */
  P_MLINK = (int)jg_envd("JG_MLINK", P_MLINK); P_LOC = (int)jg_envd("JG_LOC", P_LOC);
  P_PP = (int)jg_envd("JG_PP_HOLD", P_PP);   P_PASSIVE = (int)jg_envd("JG_PASSIVE", P_PASSIVE);
  P_PASS_N = (int)jg_envd("JG_PASS_N", P_PASS_N); P_PASS_MARGIN = jg_envd("JG_PASS_MARGIN", P_PASS_MARGIN);
  P_NOISE_DBM = jg_envd("JG_NOISE_DBM", P_NOISE_DBM); P_INR_DB = jg_envd("JG_INR_DB", P_INR_DB);  /* JGTRI */
  P_LOC_WIN = (int)jg_envd("JG_LOC_WIN", P_LOC_WIN);
  P_TRI_MIN = (int)jg_envd("JG_TRI_MIN", P_TRI_MIN); P_TRI_LTE = (int)jg_envd("JG_TRI_LTE", P_TRI_LTE); /* JGTRI2 */
  P_TRI_UMIN = (int)jg_envd("JG_TRI_UMIN", P_TRI_UMIN); /* JGTRIU */
  P_AREA_MIN = jg_envd("JG_AREA_MIN", P_AREA_MIN); P_AREA_MAX = jg_envd("JG_AREA_MAX", P_AREA_MAX);
  printf("[JamGuard] trilateration noise=%.1f dBm INR>=%.1f dB win=%d area %.0f..%.0f m\n",
         P_NOISE_DBM, P_INR_DB, P_LOC_WIN, P_AREA_MIN, P_AREA_MAX);
  printf("[JamGuard] v3 clip=%.0f pro_max=%.0f mlink=%d loc=%d pp_hold=%d passive=%d pass_n=%d pass_margin=%.1f\n",
         P_CLIP, P_PRO_MAX, P_MLINK, P_LOC, P_PP, P_PASSIVE, P_PASS_N, P_PASS_MARGIN);
  for (int c = 0; c < JG_MAX_CELL; c++) { jg_cap_now[c] = 1.0; jg_mcs_now[c] = -1; jg_cell_seen[c] = 0; }
  {
    const char* s = getenv("JG_SLICES");   /* "imsi:slice,imsi:slice,..." */
    while (s && *s) {
      int im = 0, sl = 0, n = 0;
      if (sscanf(s, "%d:%d%n", &im, &sl, &n) == 2 && im > 0 && im < JG_MAX_UE) jg_slice[im] = sl;
      const char* c = strchr(s, ',');
      s = c ? c + 1 : NULL;
    }
  }
  printf("[JamGuard] v2 slice=%d srec=%d lte_embb_max=%d embb_q=%.2f crit=%.1f/%d/%d b2_q=%.2f b1_mcs=%d poll=%ld us slices:",
         P_SLICE, P_SREC, P_LTE_EMBB_MAX, P_EMBB_Q, P_CRIT_MARGIN, P_CRIT_WAIT, P_CRIT_STAB, P_B2_Q, P_B1_MCS, P_POLL_US);
  for (int i = 1; i < JG_MAX_UE; i++) if (jg_slice[i]) printf(" %d:%d", i, jg_slice[i]);
  printf("\n");
  jg_hold = P_HOLD;
  printf("[JamGuard] policy=%d S_low=%.1f drop=%.1f P=%d K=%d S_ok=%.1f hyst=%.1f hold=%d..%d cool=%d R_min=%.0f ret_guard=%d pos=%s log=%s\n",
         P_POLICY, P_S_LOW, P_DROP, P_P, P_K, P_S_OK, P_HYST, P_HOLD, P_HOLD_MAX, P_COOL, P_R_MIN, P_RET_GUARD,
         P_POS ? P_POS : "(none)", P_LOG);
}

/* one row per decision; t_rep_s = report count x 100 ms since subscription */
static void jg_logev(long r, const char* ev, int imsi, int from, int to, const char* note)
{
  double sinr = 0, drop = 0, x = -1, y = -1;
  if (imsi > 0 && imsi < JG_MAX_UE) {
    jg_ue_t const* u = &jg_ue[imsi];
    sinr = u->sinr; drop = u->base - u->sinr;
    if (u->has_pos) { x = u->x; y = u->y; }
  }
  if (jg_log) {
    fprintf(jg_log, "%ld,%.1f,%s,%d,%d,%d,%.2f,%.2f,%.1f,%.1f,%d,%.1f,%.1f,%.1f,%s\n", r, r * 0.1, ev, imsi, from,
            to, sinr, drop, x, y, jg_have_est, jg_ex, jg_ey, jg_er, note ? note : "");
    fflush(jg_log);
  }
  printf("[JamGuard] rep %ld  %-10s UE %d  %d -> %d  SINR %.1f dB (drop %.1f)  %s\n", r, ev, imsi, from, to, sinr,
         drop, note ? note : "");
  fflush(stdout);
}

/* positioning service: file with one UE per line, numbers in columns JG_POS_COLS (imsi,x,y) */
static void jg_load_pos(void)
{
  FILE* f = fopen(P_POS, "r");
  if (f == NULL) return;
  char line[1024];
  int need = P_PC[0];
  if (P_PC[1] > need) need = P_PC[1];
  if (P_PC[2] > need) need = P_PC[2];
  while (fgets(line, sizeof line, f)) {
    double v[32];
    int n = 0;
    char* p = line;
    while (*p && n < 32) {
      char* e;
      double d = strtod(p, &e);
      if (e == p) { p++; continue; }
      v[n++] = d;
      p = e;
    }
    if (n <= need) continue;
    int imsi = (int)v[P_PC[0]];
    if (imsi <= 0 || imsi >= JG_MAX_UE) continue;
    jg_ue[imsi].x = v[P_PC[1]];
    jg_ue[imsi].y = v[P_PC[2]];
    jg_ue[imsi].has_pos = 1;
  }
  fclose(f);
}

/* simulation clock in 100 ms ticks: first field of the last line of JG_CLOCK (-1 if unknown) */
static long jg_simclock(void)
{
  FILE* f = fopen(P_CLOCK, "r");
  if (f == NULL) return -1;
  char buf[512];
  if (fseek(f, -400, SEEK_END) != 0) fseek(f, 0, SEEK_SET);
  long n = (long)fread(buf, 1, sizeof buf - 1, f);
  fclose(f);
  if (n <= 0) return -1;
  buf[n] = 0;
  long e = n - 1;
  while (e > 0 && (buf[e] == '\n' || buf[e] == '\r')) e--;
  long b = e;
  while (b > 0 && buf[b - 1] != '\n') b--;
  double t = atof(buf + b);
  return t > 0 ? (long)(t * 10.0 + 0.5) : -1;
}

static double jg_rec(meas_record_lst_t const* r) { return r->value == REAL_MEAS_VALUE ? r->real_val : (double)r->int_val; }
static double jg_db(double v) { return P_SINR_3GPP ? v / 2.0 - 23.0 : v; }

/* KPM indication: store only, decisions are taken in main() (no E2 call inside a callback) */
static void jg_on_kpm(int node, sm_ag_if_rd_t const* rd)
{
  if (rd == NULL || rd->type != INDICATION_MSG_AGENT_IF_ANS_V0 || rd->ind.type != KPM_STATS_V3_0) return;
  kpm_ind_msg_format_3_t const* m3 = &rd->ind.kpm.ind.msg.frm_3;

  pthread_mutex_lock(&mtx);
  uint64_t const jg_t_arr = time_now_us();
  /* JGROUND: a round advances only on indications with the serving-cell SINR (one per period) */
  long const r_cand = jg_node_cnt[node] + 1;
  long const r = (P_CLOCK == NULL && r_cand > jg_round) ? r_cand : jg_round;
  int jg_has_srv = 0;

  for (size_t i = 0; i < m3->ue_meas_report_lst_len; i++) {
    kpm_ind_msg_format_1_t const* f1 = &m3->meas_report_per_ue[i].ind_msg_format_1;
    if (f1->meas_info_lst_len != f1->meas_data_lst_len) continue;
    for (size_t k = 0; k < f1->meas_info_lst_len; k++) {
      meas_type_t const* mt = &f1->meas_info_lst[k].meas_type;
      meas_data_lst_t const* dl = &f1->meas_data_lst[k];
      if (mt->type != NAME_MEAS_TYPE || dl->meas_record_len == 0) continue;
      char* nm = cp_ba_to_str(mt->name);
      if (jg_kpm) {
        fprintf(jg_kpm, "%ld,%d,%s", r, node, nm);
        for (size_t j = 0; j < dl->meas_record_len; j++) fprintf(jg_kpm, ",%g", jg_rec(&dl->meas_record_lst[j]));
        fprintf(jg_kpm, "\n");
      }
      int cell = 0, imsi = 0;
      if (sscanf(nm, "L3servingSINR3gpp_cell_%d_UEID_%d", &cell, &imsi) == 2 && imsi > 0 && imsi < JG_MAX_UE) {
        jg_ue_t* u = &jg_ue[imsi];
        u->known = 1;
        u->cell = cell;
        u->sinr = jg_db(jg_rec(&dl->meas_record_lst[0]));
        if (P_CLIP > 0 && u->sinr > P_CLIP) u->sinr = P_CLIP; /* JGV3 */
        u->upd = r;
        jg_has_srv = 1;
        if (cell != P_LTE_CELL) u->last_nr_cell = cell;
        if (cell != P_LTE_CELL && cell > 0 && cell < JG_MAX_CELL) jg_cell_seen[cell] = 1;
        jg_node_cell[node] = cell;
      } else if (sscanf(nm, "L3servingRSRP_cell_%d_UEID_%d", &cell, &imsi) == 2 && imsi > 0 &&
                 imsi < JG_MAX_UE) {  /* JGTRI: ns-O-RAN KPM extension (patch_rsrp_kpm.py) */
        jg_ue[imsi].rsrp = jg_rec(&dl->meas_record_lst[0]);
        jg_ue[imsi].rsrp_r = r;
        if (cell > 0 && cell < 16) { jg_ue[imsi].nb_rsrp[cell] = jg_ue[imsi].rsrp; jg_ue[imsi].nb_rsrp_r[cell] = r; }
      } else if (sscanf(nm, "L3neighRSRP_cell_%d_UEID_%d", &cell, &imsi) == 2 && imsi > 0 &&
                 imsi < JG_MAX_UE && cell > 0 && cell < 16) {  /* JGTRI2 */
        jg_ue[imsi].nb_rsrp[cell] = jg_rec(&dl->meas_record_lst[0]);
        jg_ue[imsi].nb_rsrp_r[cell] = r;
      } else if (sscanf(nm, "L3neighSINRListOf_UEID_%d_of_Cell_%d", &imsi, &cell) == 2 && imsi > 0 &&
                 imsi < JG_MAX_UE) {
        jg_ue_t* u = &jg_ue[imsi];
        if (u->nb_round != r) { u->nb_round = r; u->nb_n = 0; }
        for (size_t j = 0; j + 1 < dl->meas_record_len && u->nb_n < JG_MAX_NB; j += 2) {
          meas_record_lst_t const* a = &dl->meas_record_lst[j];
          meas_record_lst_t const* b = &dl->meas_record_lst[j + 1];
          double s;
          int id;
          if (a->value == REAL_MEAS_VALUE) { s = a->real_val; id = (int)jg_rec(b); }
          else { id = (int)jg_rec(a); s = jg_rec(b); }
          if (id <= 0 || id == cell) continue;
          u->nb_cell[u->nb_n] = id;
          u->nb_sinr[u->nb_n] = jg_db(s);
          if (P_CLIP > 0 && u->nb_sinr[u->nb_n] > P_CLIP) u->nb_sinr[u->nb_n] = P_CLIP; /* JGV3 */
          u->nb_n++;
        }
      }
      free(nm);
    }
  }
  if (jg_has_srv) {
    jg_kpm_us = jg_t_arr;  /* arrival of the report that starts the round */
    jg_node_cnt[node] = r_cand;
    if (P_CLOCK == NULL && r_cand > jg_round) jg_round = r_cand;
  }
  if (jg_kpm) fflush(jg_kpm);
  pthread_mutex_unlock(&mtx);
}

/* one callback per E2 node, so that the node index is known */
#define JG_CB(N) static void jg_cb_##N(sm_ag_if_rd_t const* rd) { jg_on_kpm(N, rd); }
JG_CB(0) JG_CB(1) JG_CB(2) JG_CB(3) JG_CB(4) JG_CB(5) JG_CB(6) JG_CB(7)
static void (*jg_cbs[JG_MAX_NODES])(sm_ag_if_rd_t const*) = {jg_cb_0, jg_cb_1, jg_cb_2, jg_cb_3,
                                                             jg_cb_4, jg_cb_5, jg_cb_6, jg_cb_7};

static void jg_add(jg_act_t* a, int* na, int imsi, int from, int to)
{
  if (*na >= JG_MAX_ACT) return;
  a[*na].imsi = imsi; a[*na].from = from; a[*na].to = to;
  (*na)++;
}

static int jg_fresh(jg_ue_t const* u, long r) { return u->known && r - u->upd <= P_FRESH; }
/* best NR SINR of a UE: serving if on NR, else best fresh NR neighbour; no data -> +inf (old behaviour) */
static double jg_nr_sinr(jg_ue_t const* u, long r)
{
  if (u->cell != P_LTE_CELL) return u->sinr;
  double b = -1e9;
  if (r - u->nb_round <= P_FRESH)
    for (int k = 0; k < u->nb_n; k++)
      if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > b) b = u->nb_sinr[k];
  return b > -1e9 ? b : 1e9;
}

static double jg_d2(jg_ue_t const* u) { double dx = u->x - jg_ex, dy = u->y - jg_ey; return dx * dx + dy * dy; }

/* weight of a UE in the jammer position estimate */
static double jg_w(jg_ue_t const* u, long r)
{
  if (!u->has_pos) return 0;
  if (u->state == JG_NR && u->deg_cnt > 0 && jg_fresh(u, r)) return jg_clamp(u->base - u->sinr, 1, 40);
  if (u->state == JG_LTE) return u->jam_w;
  return 0;
}

static int jg_sl(int imsi) { return (imsi > 0 && imsi < JG_MAX_UE) ? jg_slice[imsi] : 0; }
static int jg_lte_embb(void)
{
  int n = 0;
  for (int i = 1; i < JG_MAX_UE; i++)
    if ((jg_ue[i].state == JG_LTE || jg_ue[i].state == JG_PROBE) && jg_sl(i) == 0) n++;
  return n;
}
/* NR SINR of a UE as seen by the emulated loop: SINR on its last NR cell (serving if on NR) */
static double jg_nr_last(jg_ue_t const* u, long r)
{
  if (u->cell != P_LTE_CELL) return u->sinr;
  if (r - u->nb_round <= P_FRESH)
    for (int k = 0; k < u->nb_n; k++)
      if (u->nb_cell[k] == u->last_nr_cell) return u->nb_sinr[k];
  return jg_nr_sinr(u, r);
}
/* eMBB cap in NR cells that serve a critical UE while the alarm is on (same rule as the emulated loop) */
static void jg_slice_step(long r)
{
  int want[JG_MAX_CELL] = {0};
  if (jg_alarm)
    for (int i = 1; i < JG_MAX_UE; i++)
      if (jg_ue[i].known && jg_sl(i) != 0 && jg_ue[i].state != JG_LTE && jg_ue[i].cell != P_LTE_CELL &&
          jg_ue[i].cell > 0 && jg_ue[i].cell < JG_MAX_CELL) want[jg_ue[i].cell] = 1;
  for (int c = 1; c < JG_MAX_CELL; c++) {
    if (!jg_cell_seen[c]) continue;
    double const q = want[c] ? P_EMBB_Q : 1.0;
    if (q == jg_cap_now[c]) continue;
    jg_cap_now[c] = q;
    char nt[64];
    snprintf(nt, sizeof nt, "cell %d eMBB max %.2f", c, q);
    jg_logev(r, q < 1.0 ? "SLICE_CAP" : "SLICE_FREE", 0, c, c, nt);
    jg_cadd(0, c, 0, q);
  }
}

/* JGV3 helpers */
static double jg_lin(double db) /* 10^(db/10) without libm, 0.1-dB steps, db in [0, 40] */
{
  double v = 1.0;
  int n = (int)(db * 10.0 + 0.5);
  if (n < 0) n = 0;
  if (n > 400) n = 400;
  for (int k = 0; k < n; k++) v *= 1.2589254117941673;
  return v;
}
static void jg_isort(double* k, double* w, int n)
{
  for (int i = 1; i < n; i++) {
    double a = k[i], b = w[i]; int j = i - 1;
    while (j >= 0 && k[j] > a) { k[j + 1] = k[j]; w[j + 1] = w[j]; j--; }
    k[j + 1] = a; w[j + 1] = b;
  }
}
/* multi-link test: a jammer near the UE lowers all its links, a blockage mostly one */
static int jg_mlink_ok(jg_ue_t const* u, long r)
{
  if (!P_MLINK || r - u->nb_round > P_FRESH) return 1;
  double d[JG_MAX_NB], w[JG_MAX_NB]; int n = 0;
  for (int k = 0; k < u->nb_n; k++) {
    int const c = u->nb_cell[k];
    if (c <= 0 || c >= 16 || c == P_LTE_CELL || u->nb_base_n[c] == 0) continue;
    d[n] = u->nb_base[c] - u->nb_sinr[k]; w[n] = 0; n++;
  }
  if (n == 0) return 1;
  jg_isort(d, w, n);
  double const med = (n % 2) ? d[n / 2] : 0.5 * (d[n / 2 - 1] + d[n / 2]);
  return med >= P_DROP / 2;
}

/* JGTRI helpers (no libm) */
static double jg_fsqrt(double v) /* v >= 1: Newton from (1+v)/2, 8 steps */
{
  double x = 0.5 * (1.0 + v);
  for (int i = 0; i < 8; i++) x = 0.5 * (x + v / x);
  return x;
}
static double jg_ln(double x) /* natural log, x > 0, no libm */
{
  if (x <= 0) return -1e30;
  int e = 0;
  while (x >= 2.0) { x *= 0.5; e++; }
  while (x < 1.0) { x *= 2.0; e--; }
  double const z = (x - 1.0) / (x + 1.0), z2 = z * z;
  double s = 0, zp = z;
  for (int k = 1; k < 30; k += 2) { s += zp / k; zp *= z2; }
  return 2.0 * s + e * 0.69314718055994531;
}
static double jg_log10(double x) { return jg_ln(x) * 0.43429448190325182; }
static double jg_exp(double y) /* e^y, no libm */
{
  int k = 0;
  while (y > 0.5) { y -= 0.69314718055994531; k++; }
  while (y < -0.5) { y += 0.69314718055994531; k--; }
  double s = 1, term = 1;
  for (int i = 1; i < 25; i++) { term *= y / i; s += term; }
  while (k > 0) { s *= 2; k--; }
  while (k < 0) { s *= 0.5; k++; }
  return s;
}
static double jg_db2lin(double db) { return jg_exp(db * 0.23025850929940457); }
/* robust (soft-l1, 6 dB) fit of J = Q - n L for fixed position; returns the cost */
static double jg_fitqn(double const* L, double const* y, int m)
{
  double w[JG_TRI_MAX], rr[JG_TRI_MAX], n = 3.0, Q = 0;
  for (int k = 0; k < m; k++) w[k] = 1.0;
  for (int it = 0; it < 6; it++) {
    double sw = 0, sl = 0, sy = 0, sll = 0, sly = 0;
    for (int k = 0; k < m; k++) { sw += w[k]; sl += w[k] * L[k]; sy += w[k] * y[k]; sll += w[k] * L[k] * L[k]; sly += w[k] * L[k] * y[k]; }
    double const den = sw * sll - sl * sl;
    n = (den > 1e-9 || den < -1e-9) ? -(sw * sly - sl * sy) / den : 3.0;
    if (n < 1.5) n = 1.5;
    if (n > 5.0) n = 5.0;
    Q = (sy + n * sl) / sw;
    for (int k = 0; k < m; k++) { rr[k] = y[k] - (Q - n * L[k]); w[k] = 1.0 / jg_fsqrt(1.0 + rr[k] * rr[k] / 36.0); }
  }
  double c = 0;
  for (int k = 0; k < m; k++) c += 72.0 * (jg_fsqrt(1.0 + rr[k] * rr[k] / 36.0) - 1.0);
  return c;
}
static double jg_tri_cost(double gx, double gy, int const* idx, int m)
{
  double L[JG_TRI_MAX], y[JG_TRI_MAX];
  for (int k = 0; k < m; k++) {
    double const dx = jg_tx[idx[k]] - gx, dy = jg_ty[idx[k]] - gy;
    double d2 = dx * dx + dy * dy;
    if (d2 < 1.0) d2 = 1.0;
    L[k] = 5.0 * jg_log10(d2);  /* 10 log10 d */
    y[k] = jg_tj[idx[k]];
  }
  return jg_fitqn(L, y, m);
}
/* JGTRIU: UE behind each observation, distinct UEs in the last fit */
static int jg_tu[JG_TRI_MAX];
static int jg_tri_nue = 0;

static int jg_trilat(double* ex, double* ey)
{
  int idx[JG_TRI_MAX], m = 0;
  for (int k = 0; k < jg_tn; k++)
    if (P_LOC_WIN <= 0 || jg_tw[k] > jg_twin - P_LOC_WIN) idx[m++] = k;
  { int seen[JG_MAX_UE] = {0}; jg_tri_nue = 0;   /* JGTRIU */
    for (int k = 0; k < m; k++) { int const u = jg_tu[idx[k]];
      if (u > 0 && u < JG_MAX_UE && !seen[u]) { seen[u] = 1; jg_tri_nue++; } } }
  if (m < 2) return 0;
  double bc = 1e30, bx = 0, by = 0;
  for (double gx = P_AREA_MIN; gx <= P_AREA_MAX + 1e-9; gx += 25.0)
    for (double gy = P_AREA_MIN; gy <= P_AREA_MAX + 1e-9; gy += 25.0) {
      double const c = jg_tri_cost(gx, gy, idx, m);
      if (c < bc) { bc = c; bx = gx; by = gy; }
    }
  double const cx = bx, cy = by;
  for (double gx = cx - 25.0; gx <= cx + 25.0 + 1e-9; gx += 5.0)
    for (double gy = cy - 25.0; gy <= cy + 25.0 + 1e-9; gy += 5.0) {
      double const c = jg_tri_cost(gx, gy, idx, m);
      if (c < bc) { bc = c; bx = gx; by = gy; }
    }
  *ex = bx; *ey = by;
  return m;
}

static void jg_evac(long r, int i, jg_act_t* a, int* na, const char* why)
{
  jg_ue_t* u = &jg_ue[i];
  int const from = u->cell;
  u->jam_w = jg_clamp(u->base - u->sinr, 1, 40);
  u->state = JG_LTE;
  u->t_evac = r;
  u->cool_until = r + P_COOL;
  u->deg_cnt = 0;
  if (jg_probe < 0 && jg_next_probe <= r) jg_next_probe = r + jg_hold;
  jg_add(a, na, i, from, P_LTE_CELL);
  jg_logev(r, "EVAC_LTE", i, from, P_LTE_CELL, why);
}

/* JGTRI2: RSRP and SINR of a UE's NR link; for a UE on the LTE anchor its last NR cell is used,
   which it still reports as a neighbour (EN-DC). Returns 0 when no fresh pair is available. */
static int jg_nr_pair(jg_ue_t const* v, long r, double* rsrp, double* sinr)
{
  if (v->state == JG_NR && v->cell != P_LTE_CELL) {
    if (!jg_fresh(v, r) || v->rsrp_r == 0 || r - v->rsrp_r > P_FRESH) return 0;
    *rsrp = v->rsrp; *sinr = v->sinr;
    return 1;
  }
  if (!P_TRI_LTE) return 0;
  int const c = v->last_nr_cell;
  if (c <= 0 || c >= 16 || c == P_LTE_CELL) return 0;
  if (v->nb_rsrp_r[c] == 0 || r - v->nb_rsrp_r[c] > P_FRESH || r - v->nb_round > P_FRESH) return 0;
  for (int k = 0; k < v->nb_n; k++)
    if (v->nb_cell[k] == c) { *rsrp = v->nb_rsrp[c]; *sinr = v->nb_sinr[k]; return 1; }
  return 0;
}

static void jg_step(long r, jg_act_t* a, int* na)
{
  char nt[96];
  if (P_POS && (r % 10 == 1 || r < 3)) jg_load_pos();

  /* 1. per-UE degradation against the UE's own baseline */
  int n_deg = 0, n_lte = 0;
  for (int i = 1; i < JG_MAX_UE; i++) {
    jg_ue_t* u = &jg_ue[i];
    if (u->state == JG_LTE) { n_lte++; continue; }
    if (u->state != JG_NR || !jg_fresh(u, r)) continue;
    if (u->upd > u->eval) {
      u->eval = u->upd;
      if (u->base_n == 0) { u->base = u->sinr; u->base_n = 1; }
      int const deg = (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) && jg_mlink_ok(u, r); /* JGV3 */
      if (deg) u->deg_cnt++;
      else {
        u->deg_cnt = 0;
        if (!jg_alarm || u->sinr >= P_S_OK) {
          u->base = (u->base_n < 10) ? (u->base * u->base_n + u->sinr) / (u->base_n + 1) : 0.9 * u->base + 0.1 * u->sinr;
          u->base_n++;
          if (r - u->nb_round <= P_FRESH)
            for (int k = 0; k < u->nb_n; k++) { /* JGV3 neighbour baselines */
              int const c = u->nb_cell[k];
              if (c <= 0 || c >= 16) continue;
              u->nb_base[c] = (u->nb_base_n[c] < 10)
                                  ? (u->nb_base[c] * u->nb_base_n[c] + u->nb_sinr[k]) / (u->nb_base_n[c] + 1)
                                  : 0.9 * u->nb_base[c] + 0.1 * u->nb_sinr[k];
              u->nb_base_n[c]++;
            }
        }
      }
    }
    if (u->deg_cnt > 0) n_deg++;
  }

  /* 2. detection: K UEs degraded for P consecutive reports */
  if (n_deg >= P_K) jg_alarm_cnt++; else jg_alarm_cnt = 0;
  if (!jg_alarm && jg_alarm_cnt >= P_P) {
    jg_alarm = 1; jg_quiet = 0; jg_lsw = jg_lsx = jg_lsy = 0; /* JGV3 */
    jg_tn = 0; jg_tri_ok = 0; jg_twin = 0; for (int q = 1; q < JG_MAX_UE; q++) jg_ue[q].wn = 0; /* JGTRI */
    snprintf(nt, sizeof nt, "%d degraded UEs", n_deg);
    jg_logev(r, "DETECT", 0, 0, 0, nt);
  }

  /* 3. localization */
  if (jg_alarm && P_LOC == 2) {
    /* JGTRI: collect J^ = S/SINR - N of UEs on NR with a fresh RSRP report */
    double const nlin = jg_db2lin(P_NOISE_DBM);
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t* v = &jg_ue[i];
      double vr, vs;
      if (!v->has_pos || v->wn >= 16 || !jg_nr_pair(v, r, &vr, &vs)) continue;   /* JGTRI2 */
      double const jl = jg_db2lin(vr) / jg_db2lin(vs) - nlin;
      if (v->wn == 0) { v->wx = 0; v->wy = 0; }
      v->wj[v->wn] = jl; v->wx += v->x; v->wy += v->y; v->wn++;
    }
    if (r % 10 == 0) {  /* end of a 1-s window */
      jg_twin++;
      int added = 0;
      for (int i = 1; i < JG_MAX_UE; i++) {
        jg_ue_t* v = &jg_ue[i];
        if (v->wn >= 5 && jg_tn < JG_TRI_MAX) {
          double tmp[16], dummy[16];
          for (int k = 0; k < v->wn; k++) { tmp[k] = v->wj[k]; dummy[k] = 0; }
          jg_isort(tmp, dummy, v->wn);
          double const jm = tmp[v->wn / 2];
          if (jm > 0 && jm >= nlin * jg_db2lin(P_INR_DB)) {
            jg_tx[jg_tn] = v->wx / v->wn; jg_ty[jg_tn] = v->wy / v->wn;
            jg_tu[jg_tn] = i; jg_tj[jg_tn] = 10.0 * jg_log10(jm); jg_tw[jg_tn] = jg_twin; jg_tn++; added++;
          }
        }
        v->wn = 0;
      }
      double ex, ey;
      int const m = jg_trilat(&ex, &ey);
      printf("[JGTRI] win %d obs %d ues %d\n", jg_twin, m, jg_tri_nue); fflush(stdout); /* JGTRIU */
      if (m >= P_TRI_MIN && jg_tri_nue >= P_TRI_UMIN) {  /* JGTRIU */  /* JGTRI2: fewer observations than unknowns -> keep the centroid */
        /* zone radius: 80th percentile of the distances of the current victim UEs, at least R_min */
        double dd[JG_MAX_UE], ww[JG_MAX_UE]; int nv = 0;
        for (int i = 1; i < JG_MAX_UE; i++) {
          jg_ue_t const* v = &jg_ue[i];
          if (!v->has_pos || v->state != JG_NR || !jg_fresh(v, r) || v->base_n == 0 || v->base - v->sinr < 3) continue;
          dd[nv] = jg_sqrt((v->x - ex) * (v->x - ex) + (v->y - ey) * (v->y - ey)); ww[nv] = 1; nv++;
        }
        double rr = P_R_MIN;
        if (nv > 0) { jg_isort(dd, ww, nv); double const q = dd[(int)(0.8 * (nv - 1))]; if (q > rr) rr = q; }
        jg_ex = ex; jg_ey = ey; jg_er = rr; jg_have_est = 1; jg_tri_ok = 1;
        snprintf(nt, sizeof nt, "%d windows (+%d), zone (%.0f, %.0f) r=%.0f m [trilat]", m, added, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      } else if (added > 0 && r % 10 == 0) {
        snprintf(nt, sizeof nt, "%d/%d observations, centroid kept [trilat-wait]", m, P_TRI_MIN);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }
    }
  }
  if (jg_alarm && (P_LOC == 1 || (P_LOC == 2 && !jg_tri_ok))) {
    /* JGV3: SINR-only weighted centroid, w = 10^(drop/10) - 1 ~ J/N, of UEs on NR with drop >= 3 dB,
       smoothed over the alarm (static jammer); radius = weighted 80th percentile */
    double sw = 0, sx = 0, sy = 0, px[JG_MAX_UE], py[JG_MAX_UE], pw[JG_MAX_UE];
    int m = 0;
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t const* v = &jg_ue[i];
      if (!v->has_pos || v->state != JG_NR || v->base_n == 0 || !jg_fresh(v, r)) continue;
      double const dr = v->base - v->sinr;
      if (dr < 3) continue;
      double const w = jg_lin(dr > 40 ? 40 : dr) - 1.0;
      sw += w; sx += w * v->x; sy += w * v->y;
      px[m] = v->x; py[m] = v->y; pw[m] = w; m++;
    }
    if (m > 0) {
      jg_lsw += sw; jg_lsx += sx; jg_lsy += sy;
      double const ex = jg_lsx / jg_lsw, ey = jg_lsy / jg_lsw;
      double dd[JG_MAX_UE];
      for (int k = 0; k < m; k++) dd[k] = jg_sqrt((px[k] - ex) * (px[k] - ex) + (py[k] - ey) * (py[k] - ey));
      jg_isort(dd, pw, m);
      double acc = 0, rr = dd[m - 1];
      for (int k = 0; k < m; k++) { acc += pw[k]; if (acc >= 0.8 * sw) { rr = dd[k]; break; } }
      if (rr < P_R_MIN) rr = P_R_MIN;
      int const moved = !jg_have_est || (ex - jg_ex) * (ex - jg_ex) + (ey - jg_ey) * (ey - jg_ey) > 25.0 ||
                        rr - jg_er > 5.0 || jg_er - rr > 5.0;
      jg_ex = ex; jg_ey = ey; jg_er = rr; jg_have_est = 1;
      if (moved) {
        snprintf(nt, sizeof nt, "%d UEs, zone (%.0f, %.0f) r=%.0f m [v3]", m, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }
    }
  } else if (jg_alarm && !(P_LOC == 2 && jg_tri_ok)) {  /* JGTRI2 */
    double sw = 0, sx = 0, sy = 0;
    int m = 0;
    for (int i = 1; i < JG_MAX_UE; i++) {
      double const w = jg_w(&jg_ue[i], r);
      if (w <= 0) continue;
      sw += w; sx += w * jg_ue[i].x; sy += w * jg_ue[i].y; m++;
    }
    if (m > 0) {
      double const ex = sx / sw, ey = sy / sw;
      double rr = 0;
      for (int i = 1; i < JG_MAX_UE; i++) {
        if (jg_w(&jg_ue[i], r) <= 0) continue;
        double const dx = jg_ue[i].x - ex, dy = jg_ue[i].y - ey;
        double const d = jg_sqrt(dx * dx + dy * dy);
        if (d > rr) rr = d;
      }
      rr += P_R_MARGIN;
      if (rr < P_R_MIN) rr = P_R_MIN;
      int const moved = !jg_have_est || (ex - jg_ex) * (ex - jg_ex) + (ey - jg_ey) * (ey - jg_ey) > 25.0 ||
                        rr - jg_er > 5.0 || jg_er - rr > 5.0;
      jg_ex = ex; jg_ey = ey; jg_er = rr; jg_have_est = 1;
      if (moved) {
        snprintf(nt, sizeof nt, "%d UEs, zone (%.0f, %.0f) r=%.0f m", m, ex, ey, rr);
        jg_logev(r, "LOCALIZE", 0, 0, 0, nt);
      }
    }
  }

  if (P_POLICY == 6) {  /* baseline B1: MCS cap in cells that serve a degraded UE while the alarm is on */
    int want[JG_MAX_CELL] = {0};
    if (jg_alarm)
      for (int i = 1; i < JG_MAX_UE; i++)
        if (jg_ue[i].known && jg_ue[i].deg_cnt > 0 && jg_ue[i].cell != P_LTE_CELL && jg_ue[i].cell > 0 &&
            jg_ue[i].cell < JG_MAX_CELL) want[jg_ue[i].cell] = 1;
    for (int c = 1; c < JG_MAX_CELL; c++) {
      if (!jg_cell_seen[c]) continue;
      int const cap = jg_alarm ? ((want[c] || jg_mcs_now[c] >= 0) ? P_B1_MCS : -1) : -1;
      if (cap == jg_mcs_now[c]) continue;
      jg_mcs_now[c] = cap;
      snprintf(nt, sizeof nt, "B1 cell %d MCS cap %d", c, cap);
      jg_logev(r, cap >= 0 ? "MCS_CAP" : "MCS_FREE", 0, c, c, nt);
      jg_cadd(1, c, 0, (double)cap);
    }
    if (jg_alarm && n_deg == 0 && ++jg_quiet >= 20) { jg_alarm = 0; jg_have_est = 0; jg_logev(r, "CLEAR", 0, 0, 0, ""); }
    return;
  }
  if (P_POLICY == 5) {  /* baseline B2: eMBB capped in all cells while the alarm is on */
    double const q = jg_alarm ? P_B2_Q : 1.0;
    if (q != jg_b2q) {
      jg_b2q = q;
      snprintf(nt, sizeof nt, "B2 eMBB max %.2f", q);
      jg_logev(r, q < 1.0 ? "SLICE_CAP" : "SLICE_FREE", 0, 0, 0, nt);
      jg_cadd(0, 0, 0, q);  /* cell 0 = all cells */
    }
    if (jg_alarm && n_deg == 0 && ++jg_quiet >= 20) { jg_alarm = 0; jg_have_est = 0; jg_logev(r, "CLEAR", 0, 0, 0, ""); }
    return;
  }
  if (P_POLICY == 0) {  /* monitor only: the RAN's own outage logic acts */
    if (jg_alarm && n_deg == 0 && ++jg_quiet >= 20) { jg_alarm = 0; jg_have_est = 0; jg_logev(r, "CLEAR", 0, 0, 0, ""); }
    return;
  }

  /* 4. mitigation */
  for (int i = 1; i < JG_MAX_UE; i++) {
    jg_ue_t* u = &jg_ue[i];
    if (u->state != JG_NR || !jg_fresh(u, r) || u->cool_until > r || u->base_n == 0) continue;
    double const drop = u->base - u->sinr;
    int const inzone = (P_POLICY == 2 && jg_have_est && u->has_pos && jg_d2(u) <= jg_er * jg_er);
    const char* why = NULL;
    if (P_POLICY == 1) {
      if (u->deg_cnt >= P_P) why = "reactive";
    } else {
      if (u->deg_cnt >= P_P && (inzone || !jg_have_est)) why = "in zone";
      else if (u->deg_cnt >= 2 * P_P) why = "persistent";
      else if (jg_alarm && inzone && drop >= P_DROP / 2 && (P_PRO_MAX <= 0 || u->sinr < P_PRO_MAX)) why = "proactive"; /* JGV3 */
    }
    if (why == NULL) continue;

    /* first choice: an NR neighbour that is clearly better; otherwise leave the jammed band */
    int best = 0;
    double bs = -1e9;
    if (r - u->nb_round <= P_FRESH)
      for (int k = 0; k < u->nb_n; k++)
        if (u->nb_cell[k] != P_LTE_CELL && u->nb_sinr[k] > bs &&
            !(P_PP > 0 && u->nb_cell[k] == u->prev_cell && r - u->ho_round < P_PP &&
              u->nb_sinr[k] < u->sinr + 2 * P_HYST)) /* JGV3 anti ping-pong */
          { bs = u->nb_sinr[k]; best = u->nb_cell[k]; }
    if (best && bs >= P_S_OK && bs >= u->sinr + P_HYST) {
      u->cool_until = r + P_COOL;
      u->deg_cnt = 0;
      u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
      jg_add(a, na, i, u->cell, best);
      snprintf(nt, sizeof nt, "%s, neighbour %.1f dB", why, bs);
      jg_logev(r, "HO_NR", i, u->cell, best, nt);
    } else if (P_SLICE && jg_sl(i) == 0 && jg_lte_embb() >= P_LTE_EMBB_MAX) {
      /* LTE anchor reserved for critical slices: keep eMBB on NR (best neighbour if better, else stay) */
      u->cool_until = r + P_COOL;
      if (best && bs >= u->sinr + P_HYST) {
        u->deg_cnt = 0;
        u->prev_cell = u->cell; u->ho_round = r; /* JGV3 */
        jg_add(a, na, i, u->cell, best);
        snprintf(nt, sizeof nt, "%s, eMBB kept on NR, neighbour %.1f dB", why, bs);
        jg_logev(r, "HO_NR", i, u->cell, best, nt);
      } else
        jg_logev(r, "HOLD_NR", i, u->cell, u->cell, "eMBB, LTE anchor reserved for critical slices");
    } else {
      jg_evac(r, i, a, na, why);
      n_lte++;
    }
  }

  /* 5a. JGV3 passive recovery: UEs on the LTE anchor keep reporting their NR SINR (EN-DC neighbour list);
         the jammer is declared gone when enough of them see a good NR link and no NR UE is degraded */
  if (P_PASSIVE && jg_probe < 0 && !jg_returning && n_lte > 0 && r >= jg_next_probe) { /* JGPASS2 hold */
    int need = n_lte < 2 ? n_lte : 2;
    if (need < (n_lte + 1) / 2) need = (n_lte + 1) / 2; /* JGPASS2 majority of evacuated UEs */
    int okn = 0;
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t* v = &jg_ue[i];
      if (v->state != JG_LTE) continue;
      if (v->nb_round != v->pass_r) {   /* one count per new neighbour report */
        v->pass_r = v->nb_round;
        if (r - v->nb_round <= P_FRESH && jg_nr_last(v, r) >= P_S_OK + P_PASS_MARGIN && jg_nr_last(v, r) < 1e8) v->pass_ok++;
        else v->pass_ok = 0;
      }
      if (v->pass_ok >= P_PASS_N) okn++;
    }
    if (n_deg == 0 && okn >= need) {
      snprintf(nt, sizeof nt, "%d evacuated UEs see NR SINR >= %.0f dB", okn, P_S_OK + P_PASS_MARGIN);
      jg_logev(r, "PASSIVE_OK", 0, P_LTE_CELL, 0, nt);
      jg_probe_ok_r = r;
      jg_returning = 1; jg_alarm = 0; jg_alarm_cnt = 0; jg_have_est = 0; jg_hold = P_HOLD;
      for (int i = 1; i < JG_MAX_UE; i++) jg_ue[i].pass_ok = 0;
    }
  }

  /* 5. recovery: probe one UE back to NR, exponential back-off if the jammer is still there */
  if (jg_probe > 0) {
    jg_ue_t* u = &jg_ue[jg_probe];
    if (u->upd > u->eval && u->upd > u->probe_since + 1) {
      u->eval = u->upd;
      double const ok_th = (u->base - P_DROP / 2 < P_S_OK) ? u->base - P_DROP / 2 : P_S_OK; /* as emulated loop */
      if (u->sinr >= ok_th) u->ok_cnt++;
      else if (u->sinr < P_S_LOW && u->base - u->sinr >= P_DROP) u->bad_cnt++;
    }
    /* sentinel check (JG_SREC): UEs still on NR that are degraded show that the jammer is still there */
    if (P_SREC && n_deg > 0 && u->ok_cnt >= 5) {
      u->ok_cnt = 0;
      if (r % 10 == 0) jg_logev(r, "PROBE_HOLD", jg_probe, P_LTE_CELL, u->cell, "sentinel UEs on NR still degraded");
    }
    if (u->ok_cnt >= 5) {
      u->state = JG_NR; u->deg_cnt = 0; u->cool_until = r + P_COOL;
      jg_logev(r, "PROBE_OK", jg_probe, P_LTE_CELL, u->cell, "jammer gone, returning UEs");
      jg_probe_ok_r = r;
      jg_probe = -1; jg_returning = 1; jg_alarm = 0; jg_alarm_cnt = 0; jg_have_est = 0; jg_hold = P_HOLD;
    } else if (u->bad_cnt >= 2 || r - u->probe_since > 20) {
      jg_hold = (2 * jg_hold > P_HOLD_MAX) ? P_HOLD_MAX : 2 * jg_hold;
      u->state = JG_LTE; u->t_evac = r; u->cool_until = r + P_COOL;
      jg_add(a, na, jg_probe, u->cell, P_LTE_CELL);
      snprintf(nt, sizeof nt, "jammer still on, next probe in %ld reports", jg_hold);
      jg_logev(r, "PROBE_FAIL", jg_probe, u->cell, P_LTE_CELL, nt);
      jg_next_probe = r + jg_hold;
      jg_probe = -1;
    }
  } else if (!jg_returning && n_lte > 0 && r >= jg_next_probe && P_PASSIVE != 2) { /* JGV3 */
    int p = -1;
    double bd = 1e18;
    long bt = 1L << 60;
    for (int i = 1; i < JG_MAX_UE; i++) {
      jg_ue_t const* u = &jg_ue[i];
      if (u->state != JG_LTE) continue;
      if (P_SREC && jg_sl(i) != 0 && jg_lte_embb() > 0) continue;  /* probe with eMBB only */
      if (P_POLICY == 2 && jg_have_est && u->has_pos) { if (jg_d2(u) < bd) { bd = jg_d2(u); p = i; } }
      else if (bd >= 1e18 && u->t_evac < bt) { bt = u->t_evac; p = i; }
    }
    if (p > 0) {
      jg_ue_t* u = &jg_ue[p];
      u->state = JG_PROBE; u->probe_since = r; u->ok_cnt = 0; u->bad_cnt = 0; u->eval = u->upd;
      jg_add(a, na, p, P_LTE_CELL, u->last_nr_cell);
      jg_logev(r, "PROBE", p, P_LTE_CELL, u->last_nr_cell,
               (P_POLICY == 2 && bd < 1e18) ? "UE nearest to the jammer estimate" : "first evacuated UE");
      jg_probe = p;
    }
  }

  if (jg_returning) {
    if (jg_alarm) { /* JGPASS2: recovery was wrong, back off before trying again */
      jg_returning = 0;
      jg_hold = (2 * jg_hold > P_HOLD_MAX) ? P_HOLD_MAX : 2 * jg_hold;
      jg_next_probe = r + jg_hold;
      jg_logev(r, "RECOVER_FAIL", 0, 0, 0, "jammer still on after recovery, backing off");
    }
    else {
      int done = 1, embb_left = 0;
      if (P_SREC)
        for (int j = 1; j < JG_MAX_UE; j++) {
          if (jg_ue[j].state != JG_LTE) continue;
          if (jg_sl(j) == 0) embb_left++;
          else jg_ue[j].stab = (jg_nr_last(&jg_ue[j], r) >= P_S_OK + P_CRIT_MARGIN) ? jg_ue[j].stab + 1 : 0;
        }
      for (int i = 1; i < JG_MAX_UE; i++) {
        jg_ue_t* u = &jg_ue[i];
        if (u->state != JG_LTE) continue;
        done = 0;
        if (P_SREC && jg_sl(i) != 0 &&
            (embb_left > 0 || r - jg_probe_ok_r < P_CRIT_WAIT || u->stab < P_CRIT_STAB)) continue; /* critical last */
        if (P_RET_GUARD && jg_nr_last(u, r) < P_S_OK) continue;  /* NR link still poor: keep on LTE */
        u->state = JG_NR; u->deg_cnt = 0; u->cool_until = r + P_COOL; u->eval = u->upd;
        jg_add(a, na, i, P_LTE_CELL, u->last_nr_cell);
        jg_logev(r, "RETURN", i, P_LTE_CELL, u->last_nr_cell, "");
        break;  /* one UE per report, no handover storm */
      }
      if (done) jg_returning = 0;
    }
  }

  if (jg_alarm && n_deg == 0 && n_lte == 0 && jg_probe < 0) {
    if (++jg_quiet >= 20) { jg_alarm = 0; jg_have_est = 0; jg_logev(r, "CLEAR", 0, 0, 0, ""); }
  } else jg_quiet = 0;
  if (P_SLICE && P_POLICY > 0 && P_POLICY < 5) jg_slice_step(r);
}

static void jg_send(int imsi, int from, int to)
{
  if (to < 1 || to > 9) { printf("[JamGuard] invalid target cell %d\n", to); return; }
  int idx = -1;
  for (int k = 0; k < (int)jg_nodes.len && k < JG_MAX_NODES; k++)
    if (from != P_LTE_CELL && jg_node_cell[k] == from) { idx = k; break; }
  if (idx < 0)
    for (int k = 0; k < (int)jg_nodes.len && k < JG_MAX_NODES; k++)
      if (jg_node_cell[k] >= 1 && jg_node_cell[k] != P_LTE_CELL) { idx = k; break; }
  if (idx < 0) idx = 0;

  rc_ctrl_req_data_t rc = {0};
  ue_id_e2sm_t uid = gen_rc_ue_id(GNB_UE_ID_E2SM, imsi);
  rc.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, uid, CONNECTED_MODE_MOBILITY, HANDOVER_CONTROL_7_6_4_1);
  rc.msg = gen_handover_rc_ctrl_msg(FORMAT_1_E2SM_RC_CTRL_MSG, (uint8_t)('0' + to));
  uint64_t const t0 = time_now_us();
  sm_ans_xapp_t ans = control_sm_xapp_api(&jg_nodes.n[idx].id, SM_RC_ID, &rc);
  uint64_t const t1 = time_now_us();
  if (jg_lat) {
    fprintf(jg_lat, "%ld,HO,%d,%d,%llu,%llu,%llu,%d\n", jg_round, imsi, to, (unsigned long long)jg_kpm_us,
            (unsigned long long)t0, (unsigned long long)t1, ans.success ? 1 : 0);
    fflush(jg_lat);
  }
  printf("[JamGuard] RC Handover_Control UE %d -> cell %d via E2 node %d (cell %d): %s\n", imsi, to, idx,
         jg_node_cell[idx], ans.success ? "sent" : "FAILED");
  fflush(stdout);
  /* rc is not freed, as in xapp_manual_ho.c */
}

/* cell-level control over E2SM-RC style 2 (Radio Resource Allocation Control)
   kind 0: slice-level PRB quota (action 6), kind 1: DL MCS cap (vendor-specific action 100) */
static void jg_send_cell(int kind, int cell, int slice, double val)
{
  long long v;
  uint16_t act;
  /* JGCMD2: reserved UE id in the Connected-Mode-Mobility format (style 2 is not acknowledged by e2sim) */
  if (kind == 0) { act = 6;   v = 100000000LL + (long long)cell * 1000000LL + (long long)slice * 10000LL + (long long)(val * 1000.0 + 0.5); }
  else           { act = 100; v = 110000000LL + (long long)cell * 1000000LL + (long long)((int)val + 1); }
  int idx = -1;
  for (int k = 0; k < (int)jg_nodes.len && k < JG_MAX_NODES; k++)
    if (cell > 0 && jg_node_cell[k] == cell) { idx = k; break; }
  if (idx < 0)
    for (int k = 0; k < (int)jg_nodes.len && k < JG_MAX_NODES; k++)
      if (jg_node_cell[k] >= 1 && jg_node_cell[k] != P_LTE_CELL) { idx = k; break; }
  if (idx < 0) idx = 0;
  rc_ctrl_req_data_t rc = {0};
  ue_id_e2sm_t uid = gen_rc_ue_id(GNB_UE_ID_E2SM, (int)v);
  rc.hdr = gen_rc_ctrl_hdr(FORMAT_1_E2SM_RC_CTRL_HDR, uid, CONNECTED_MODE_MOBILITY, HANDOVER_CONTROL_7_6_4_1);
  rc.msg = gen_handover_rc_ctrl_msg(FORMAT_1_E2SM_RC_CTRL_MSG, (uint8_t)('0' + ((cell >= 0 && cell <= 9) ? cell : 0)));
  uint64_t const t0 = time_now_us();
  sm_ans_xapp_t ans = control_sm_xapp_api(&jg_nodes.n[idx].id, SM_RC_ID, &rc);
  uint64_t const t1 = time_now_us();
  printf("[JamGuard] RC cell command %u cell %d %s %.2f (value %lld) via E2 node %d: %s\n", act, cell,
         kind == 0 ? "eMBB ratio" : "MCS cap", val, v, idx, ans.success ? "sent" : "FAILED");
  fflush(stdout);
  if (jg_lat) {
    fprintf(jg_lat, "%ld,%s,%d,%lld,%llu,%llu,%llu,%d\n", jg_round, kind == 0 ? "SLICE" : "MCS", cell, v,
            (unsigned long long)jg_kpm_us, (unsigned long long)t0, (unsigned long long)t1, ans.success ? 1 : 0);
    fflush(jg_lat);
  }
}

static void jg_sig(int s) { (void)s; jg_stop = 1; }

int main(int argc, char* argv[])
{
  jg_params();
  jg_log = fopen(P_LOG, "w");
  if (jg_log)
    fprintf(jg_log, "rep,t_rep_s,event,imsi,from_cell,to_cell,sinr_db,drop_db,ue_x,ue_y,est_ok,est_x,est_y,est_r,note\n");

  if (getenv("JG_LAT")) {
    jg_lat = fopen(getenv("JG_LAT"), "w");
    if (jg_lat) fprintf(jg_lat, "rep,kind,ue_or_cell,target_or_value,t_kpm_us,t_start_us,t_end_us,ok\n");
    printf("[JamGuard] latency log to %s\n", getenv("JG_LAT"));
  }
  if (getenv("JG_KPM_DUMP")) {
    jg_kpm = fopen(getenv("JG_KPM_DUMP"), "w");
    if (jg_kpm) fprintf(jg_kpm, "rep,node,meas_name,values...\n");
    printf("[JamGuard] KPM dump to %s\n", getenv("JG_KPM_DUMP"));
  }
  fr_args_t args = init_fr_args(argc, argv);
  init_xapp_api(&args);
  sleep(1);
  signal(SIGINT, jg_sig);
  signal(SIGTERM, jg_sig);

  jg_nodes = e2_nodes_xapp_api();
  assert(jg_nodes.len > 0);
  printf("[JamGuard] connected E2 nodes = %d\n", (int)jg_nodes.len);
  pthread_mutex_init(&mtx, NULL);

  sm_ans_xapp_t hndl[JG_MAX_NODES];
  int has[JG_MAX_NODES] = {0};
  for (size_t i = 0; i < jg_nodes.len && i < JG_MAX_NODES; i++) {
    e2_node_connected_xapp_t* n = &jg_nodes.n[i];
    size_t idx = n->len_rf;
    for (size_t k = 0; k < n->len_rf; k++)
      if (n->rf[k].id == SM_KPM_ID) idx = k;
    if (idx == n->len_rf) { printf("[JamGuard] node %zu: no KPM\n", i); continue; }
    kpm_ran_function_def_t const* kd = &n->rf[idx].defn.kpm;
    if (kd->ric_report_style_list == NULL || kd->ric_event_trigger_style_list == NULL ||
        get_kpm_act_def[kd->ric_report_style_list[0].report_style_type] == NULL) {
      printf("[JamGuard] node %zu: KPM report style not supported, skipped\n", i);
      continue;
    }
    kpm_sub_data_t sub = gen_kpm_subs(kd);
    hndl[i] = report_sm_xapp_api(&n->id, SM_KPM_ID, &sub, jg_cbs[i]);
    has[i] = hndl[i].success;
    printf("[JamGuard] node %zu: KPM subscription %s\n", i, has[i] ? "ok" : "FAILED");
  }

  long last = 0;
  while (!jg_stop) {
    usleep((useconds_t)P_POLL_US);
    jg_act_t acts[JG_MAX_ACT];
    int na = 0;
    long const ck = P_CLOCK ? jg_simclock() : -1;
    pthread_mutex_lock(&mtx);
    if (ck > jg_round) jg_round = ck;
    long const r = jg_round;
    jg_cact_t cacts[32];
    int nca = 0;
    uint64_t td0 = 0, td1 = 0, tk = 0;
    if (r > last) {
      last = r;
      jg_ncq = 0;
      tk = jg_kpm_us;
      td0 = time_now_us();
      jg_step(r, acts, &na);
      td1 = time_now_us();
      nca = jg_ncq;
      for (int k = 0; k < nca; k++) cacts[k] = jg_cq[k];
      jg_ncq = 0;
    }
    pthread_mutex_unlock(&mtx);
    if (jg_lat && td1 > 0 && (na > 0 || nca > 0)) {
      fprintf(jg_lat, "%ld,DECIDE,%d,%d,%llu,%llu,%llu,1\n", r, na, nca, (unsigned long long)tk,
              (unsigned long long)td0, (unsigned long long)td1);
      fflush(jg_lat);
    }
    for (int k = 0; k < na; k++) jg_send(acts[k].imsi, acts[k].from, acts[k].to);
    for (int k = 0; k < nca; k++) jg_send_cell(cacts[k].kind, cacts[k].cell, cacts[k].slice, cacts[k].val);
    if (P_ROUNDS > 0 && r >= P_ROUNDS) break;
  }

  printf("[JamGuard] stopping after %ld reports\n", last);
  for (size_t i = 0; i < jg_nodes.len && i < JG_MAX_NODES; i++)
    if (has[i]) rm_report_sm_xapp_api(hndl[i].u.handle);
  if (jg_log) fclose(jg_log);
  fflush(stdout);
  while (try_stop_xapp_api() == false) usleep(1000);
  return 0;
}
