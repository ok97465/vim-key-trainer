"""외부 사전 없이 사용하는 자체 작성 ASCII 연습 어휘.

단어 선택은 주입한 난수원만 사용한다. 코드 식별자용 어휘는 원문과
이미 할당한 이름 사이의 부분 문자열 충돌도 제외해 검색 위치를 보존한다.
"""

# Standard library imports
from collections.abc import Collection
from random import Random

PRACTICE_WORDS: tuple[str, ...] = tuple(
    """
    acorn actor admiral agate airship album alcove almond alpine amber anchor
    anemone angel angle animal anise ankle antelope apple apron arbor arcade
    archer archive arena arrow artist aspen atlas attic auburn aurora autumn
    avenue avocado azalea badger bagel bakery balcony bamboo banana banner
    barley barrel basket beacon beaker beaver bedroom beetle berry bicycle
    birch biscuit bison blanket blossom blueberry boardwalk bonnet bookcase
    bottle boulder bracelet branch brass breeze bridge broccoli bronze brook
    broom bubble bucket buckle buffalo building bulb bunting burrow butter
    button cabin cactus candle canyon captain caramel cardinal cargo carpet
    carrot carton cascade castle cedar celery cellar ceramic cereal chalk
    chamber chapel cherry chestnut chickadee chimney chocolate choral cinnamon
    circle citrus clay clematis cliff cloak clover cobalt coconut coffee collar
    comet compass concert copper coral cottage cotton country courtyard coyote
    cracker crane crate crayon creek crescent cricket crimson crocus crown
    crystal cucumber cushion cypress daffodil dahlia daisy dancer dandelion dawn
    daylight denim desert diamond diary dolphin domino donkey doorway dragon
    dragonfly drawer driftwood drizzle droplet drum duckling dune dusk eagle
    earring easel echo elderberry elephant elevator emerald enamel engine falcon
    family feather fennel fern ferry festival fiddle field finch firefly fir
    flag flannel fleece flight floral flute fog folder forest fossil fountain
    foxglove freesia frost fruit galaxy gallery garden garlic garnet gazebo
    gentian ginger giraffe glacier glass glider globe glove golden goose granite
    grape graphite grass gravel greenhouse grove guitar gull harbor harmonica
    harvest hazel hearth heather hedgehog helmet heron hibiscus hickory hillside
    holly honey horizon hornet hyacinth iceberg igloo indigo insect island ivory
    jacket jaguar jasmine jelly jewel journey juniper kettle keyboard kite
    kitten kiwi koala lagoon lantern larch lark lattice laurel lavender leaf
    leather lemon lemur lentil leopard letter lettuce library lilac lily lime
    linen lizard llama lobster locust lodge lotus luggage lumber lunar lynx
    lyre magnet magnolia mahogany maize mango maple marble marigold market
    marmot marsh meadow melon mercury meridian mica midnight millet mineral
    mirror mist mitten mocha monarch moonlight morning mosaic moth mountain
    mulberry mushroom mustard myrtle narwhal nectar needle nephew nickel night
    notebook nutmeg oasis oatmeal ocean ochre octagon octopus olive onion opal
    orange orchard orchid oregano oriole otter oyster paddle pagoda painter
    palace palm panda pantry papaya paper parcel parsley parsnip passage pasta
    pasture patchwork peach peanut pearl pebble pecan pelican pencil peony
    pepper petal pewter pheasant piano picnic pigeon pillow pine pineapple
    pipit pistachio pitcher planet plantain platter plaza plum pocket pond
    poplar poppy porcelain porch potato prairie prism pumpkin puppet purple
    puzzle quartz queen quince rabbit raccoon radish raft rainbow raisin raven
    reed reef reindeer ribbon ridge river robin rocket rosemary rosewood rowan
    ruby saffron sage sailboat sailor salad salmon sandal sapphire satin saucer
    savanna scarf school scissors seagull seahorse seashell season seedling
    sesame shadow shamrock shark shawl shepherd shield shore shovel shrimp
    shuttle sienna silver slate slipper snail snowflake soap soldier sorrel
    sparrow spearmint spider spinach spiral sponge spoon spring spruce square
    squirrel stadium staircase starling station statue steeple stone storeroom
    strawberry stream street studio sugar suitcase summer sunflower sunrise
    sunset swallow sweater sycamore table tamarind tangerine tapestry tartan
    teapot temple terrace thistle thorn thread thyme ticket timber toffee tomato
    topaz tortoise tower tractor trail train tray trellis triangle trumpet tulip
    tunnel turquoise turtle twilight umbrella valley vanilla velvet veranda
    violet violin visitor walnut walrus waterfall wax weasel weather wheat
    wheel whisper willow window winter wisteria woodland workshop wren yacht
    yam yarn yellow yogurt zebra zinnia
    """.split()
)


def practice_word(rng: Random, *, exclude: Collection[str] = ()) -> str:
    """제외한 단어와 다른 소문자 영단어를 재현 가능하게 고른다."""
    choices = tuple(word for word in PRACTICE_WORDS if word not in exclude)
    if not choices:
        raise ValueError("선택할 수 있는 연습 단어가 없습니다.")
    return rng.choice(choices)


class IdentifierPool:
    """원문·다른 손상 이름과 겹치지 않는 검색 가능한 식별자를 할당한다."""

    def __init__(self, rng: Random, lines: tuple[str, ...]) -> None:
        self._rng = rng
        self._original = "\n".join(lines).casefold()
        self._assigned: list[str] = []
        self._available = [
            word for word in PRACTICE_WORDS if word not in self._original
        ]
        rng.shuffle(self._available)

    def take(self) -> str:
        # 보통은 단어 하나를 사용하고 일부는 서로 다른 표기의 복합 이름을 쓴다.
        # 긴 문서에서도 행 번호나 고정 접두사를 붙여 이름을 만들지 않는다.
        for _ in range(4096):
            if self._available and self._rng.randrange(5):
                candidate = self._available.pop()
            else:
                left, right = self._rng.sample(PRACTICE_WORDS, 2)
                style = self._rng.randrange(3)
                candidate = (
                    f"{left}_{right}"
                    if style == 0
                    else left + (right.title() if style == 1 else right)
                )
            normalized = candidate.casefold()
            if normalized in self._original or any(
                normalized in name or name in normalized for name in self._assigned
            ):
                continue
            self._assigned.append(normalized)
            return candidate
        raise ValueError("원문과 겹치지 않는 연습 식별자를 만들 수 없습니다.")
