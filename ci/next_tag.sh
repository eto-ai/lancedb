# Determine the next tag to use for a release
CURRENT_VERSION=$1
RELEASE_TYPE=$2
PREFIX=${3:-}

if [ "$RELEASE_TYPE" == "stable" ]; then
  TAG="v${CURRENT_VERSION}"
else
  # Get a list of all tags, filter for current version beta tags, sort them and get the last one
  LAST_BETA_TAG=$(git tag | grep "^${PREFIX}v${CURRENT_VERSION}-beta." | sort -V | tail -n 1)

  if [ -z "$LAST_BETA_TAG" ]; then
    # If there are no existing beta tags for the current version, start with beta.1
    NEXT_BETA_TAG="${PREFIX}v${CURRENT_VERSION}-beta.1"
  else
    # If there are existing beta tags, increment the last beta number to get the next one
    LAST_BETA_NUMBER=$(echo $LAST_BETA_TAG | sed "s/v${CURRENT_VERSION}-beta.//")
    NEXT_BETA_NUMBER=$((LAST_BETA_NUMBER + 1))
    NEXT_BETA_TAG="${PREFIX}v${CURRENT_VERSION}-beta.${NEXT_BETA_NUMBER}"
  fi
  TAG=$NEXT_BETA_TAG
fi

echo $TAG