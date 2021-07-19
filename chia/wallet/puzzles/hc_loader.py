from chia.wallet.puzzles.load_clvm import load_clvm

HC_MOD = load_clvm("hc.clvm", package_or_requirement=__name__)
#LOCK_INNER_PUZZLE = load_clvm("lock.inner.puzzle.clvm", package_or_requirement=__name__)

def main():
    print(HC_MOD)

if __name__ == '__main__':
    main()