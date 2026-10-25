#include <vector>

namespace auth {

/// Manages sessions.
template <typename T>
class SessionManager : public Base {
 public:
  explicit SessionManager(Store* s) : store_(s) {}
  void ExpireOld(int now);
  int count() const { return all().size(); }
 private:
  int timeout_ = 30;
};

template <typename T>
void SessionManager<T>::ExpireOld(int now) {
  auto is_old = [&](const Session& s) { return s.Age(now) > timeout_; };
  for (auto& s : all()) if (is_old(s)) RevokeSession(s.id);
}

void RevokeSession(const std::string& id) { db::sessions().Delete(id); }

}  // namespace auth

extern "C" { int c_api(void) { return 0; } }

__global__ void kernel(float* x) { x[threadIdx.x] = 0; }

TEST(UsersTest, DisableUser) { DisableUser(u); }
