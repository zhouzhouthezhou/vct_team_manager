import random

def assign_regions(json_input, more_than_two_regions):
    # List of potential regions for each value
    regions_dict = {
        "vct-international": ['vct_pacific', 'vct_emea', 'vct_china', 'vct_americas'],
        "vct-challengers": ['challengers_pacific', 'challengers_americas', 'challengers_emea'],
        "game-changers": ['game_changers_pacific', 'game_changers_americas', 'game_changers_emea']
    }

    values = list(json_input.values())
    roles = list(json_input.keys())
    
    assigned_regions = []

    all_same = len(set(values)) == 1

    if all_same:
        event_type = values[0]
        potential_regions = regions_dict[event_type]

        if not more_than_two_regions:
            # Ensure at least 4 regions are the same
            main_region = random.choice(potential_regions)
            assigned_regions = [main_region] * 4 + [random.choice(potential_regions)]
            random.shuffle(assigned_regions)
        else:
            # Ensure at least 3 regions are different
            assigned_regions = random.sample(potential_regions, 3) + [random.choice(potential_regions)] * 2
            random.shuffle(assigned_regions)

    else:
        # Handle case when values are not all the same
        if not more_than_two_regions:
            for role in roles:
                event_type = json_input[role]
                region = random.choice(regions_dict[event_type])
                assigned_regions.append(region)
        else:
            # Ensure at least 3 regions are unique
            regions = []
            for role in roles:
                event_type = json_input[role]
                region = random.choice(regions_dict[event_type])
                regions.append(region)
            unique_regions = list(set(regions))
            
            if len(unique_regions) >= 3:
                assigned_regions = regions
            else:
                while len(unique_regions) < 3:
                    extra_region = random.choice(random.choice(list(regions_dict.values())))
                    if extra_region not in unique_regions:
                        unique_regions.append(extra_region)
                assigned_regions = regions[:3] + random.sample(unique_regions, 2)
                random.shuffle(assigned_regions)
    
    return assigned_regions