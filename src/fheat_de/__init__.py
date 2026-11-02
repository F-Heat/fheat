"""What every German state adapter can share.

Like :mod:`fheat_eu` nothing here depends on a federal state:

- :mod:`fheat_de.mastr`, :mod:`fheat_de.biogas`: biogas CHP units of the
  Marktstammdatenregister and their clusters (files of all Germany, cut to
  any area);
- :mod:`fheat_de.alkis`: ALKIS land use → civil works factor, the columns of
  the "ALKIS vereinfacht" buildings (AdV, the same in every state);
- :mod:`fheat_de.osm_surface`: OSM road surfaces → civil works factor, and
  their download from the Overpass API;
- :mod:`fheat_de.heat_demand`: heat demand, full load hours and load profile
  of a building from its ALKIS function and age class;
- :mod:`fheat_de.lod2`: buildings of a CityGML LoD2 tile (height, eaves
  height, footprint);
- :mod:`fheat_de.zensus`: age class of a building from the Zensus 2022 grid;
- :mod:`fheat_de.area`: the area catalogue ``cities.csv``, district outlines
  from parcels;
- :mod:`fheat_de.streets`: streets as the core expects them.

Where a state serves its data (URLs, tiles, catalogue of its municipalities)
stays in its own package, e.g. :mod:`fheat_nrw`, :mod:`fheat_nds`.
"""
