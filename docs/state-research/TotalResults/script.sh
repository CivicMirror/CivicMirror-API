#!/usr/bin/env bash

API="https://enr-results-api.totalresults.com/Election/GetElectionList"

clients=(
arkansas
alabama
alaska
arizona
california
colorado
connecticut
delaware
florida
georgia
hawaii
idaho
illinois
indiana
iowa
kansas
kentucky
louisiana
maine
maryland
massachusetts
michigan
minnesota
mississippi
missouri
montana
nebraska
nevada
newhampshire
newjersey
newmexico
newyork
northcarolina
northdakota
ohio
oklahoma
oregon
pennsylvania
rhodeisland
southcarolina
southdakota
tennessee
texas
utah
vermont
virginia
washington
westvirginia
wisconsin
wyoming
)

printf "%-20s %-8s %s\n" "CLIENT" "COUNT" "SAMPLE"

for cid in "${clients[@]}"; do

    result=$(curl -s "$API?cId=$cid" --max-time 15)

    count=$(echo "$result" | jq 'length' 2>/dev/null)

    if [[ "$count" =~ ^[0-9]+$ ]] && [ "$count" -gt 0 ]; then

        sample=$(echo "$result" | jq -r '.[0].electionName')

        printf "%-20s %-8s %s\n" "$cid" "$count" "$sample"
    fi

    sleep 0.15
done
