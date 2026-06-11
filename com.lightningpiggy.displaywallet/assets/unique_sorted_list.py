# keeps a list of items
# The .add() method ensures the list remains unique (via __eq__)
# and sorted (via __lt__) by inserting new items in the correct position.
class UniqueSortedList:

    # Hard cap on retained items. The display never shows more than the
    # "Transactions Shown" slider's max (21), but `Wallet.handle_new_payment`
    # — fed by LNBits websocket pushes and NWC notifications — adds to this
    # list for as long as the app runs. Without a cap, a busy wallet's list
    # (and its on-disk cache copy) grows unboundedly on ESP32 RAM. The list
    # is sorted descending (newest first), so trimming the tail drops the
    # oldest entries.
    MAX_ITEMS = 50

    def __init__(self):
        self._items = []

    def add(self, item):
        # Check if item already exists (using __eq__)
        if item not in self._items:
            # Insert item in sorted position for descending order (using __gt__)
            for i, existing_item in enumerate(self._items):
                if item > existing_item:
                    self._items.insert(i, item)
                    break
            else:
                # If item is smaller than all existing items, append it
                self._items.append(item)
            if len(self._items) > self.MAX_ITEMS:
                self._items = self._items[:self.MAX_ITEMS]

    def __iter__(self):
        # Return iterator for the internal list
        return iter(self._items)

    def get(self, index_nr):
        # Retrieve item at given index, raise IndexError if invalid
        try:
            return self._items[index_nr]
        except IndexError:
            raise IndexError("Index out of range")

    def __len__(self):
        # Return the number of items for len() calls
        return len(self._items)

    def __str__(self):
        #print("UniqueSortedList tostring called")
        return "\n".join(str(item) for item in self._items)

    def head_str(self, n):
        """Return the multi-line display string of just the first `n`
        items (the largest, since the list is sorted descending). Used
        to honour a user-set cap on visible transactions (Customise →
        Transactions Shown) without rebuilding the underlying list.
        `n <= 0` returns an empty string; `n >= len(self)` is equivalent
        to `str(self)`."""
        if n <= 0 or len(self._items) == 0:
            return ""
        if n >= len(self._items):
            return self.__str__()
        return "\n".join(str(item) for item in self._items[:n])

    def __eq__(self, other):
        # Comparing against None / non-iterables must yield "not equal",
        # not a TypeError from len(other).
        try:
            if len(self._items) != len(other):
                return False
            return all(p1 == p2 for p1, p2 in zip(self._items, other))
        except TypeError:
            return NotImplemented
