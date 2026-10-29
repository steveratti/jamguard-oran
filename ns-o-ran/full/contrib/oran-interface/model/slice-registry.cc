#include "slice-registry.h"
namespace ns3 {
SliceRegistry& SliceRegistry::Instance() { static SliceRegistry inst; return inst; }
}
