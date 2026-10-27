#include "store.hpp"

namespace store {

struct Entry;
struct Entry *first_entry;

int add(int a, int b) {
    return a + b;
}

class Store {
public:
    int &count() { return count_; }
    ~Store();
    struct Options {
        bool load() const { return true; }
    };
private:
    int count_ = 0;
};

Store::~Store() {
    clear();
}

template <class T>
T *Cache<T>::get(const std::string &key) const {
    auto check = [](int x) { return x > 0; };
    return lookup(key);
}

bool Store::operator==(const Store &other) const {
    return count_ == other.count_;
}

Store::operator bool() const {
    return count_ > 0;
}

namespace detail {
void flush::run(int n) {
    write(n);
}
}  // namespace detail

}  // namespace store
